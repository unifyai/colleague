#!/usr/bin/env python3
"""Send overdue-invoice reminders and post the next weekly digest."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, NoReturn

BASE_URL = "http://127.0.0.1:8182"
TIMEOUT_SECONDS = 30
EXPECTED_INVOICE_FIELDS = {
    "id",
    "vendor",
    "amount_cents",
    "currency",
    "days_overdue",
    "contact_email",
}


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def hold(reason: str) -> NoReturn:
    message = "HOLD: " + " ".join(reason.split())[:1800]
    try:
        request_json("POST", "/owner/notify", {"message": message})
    except Exception as exc:
        print(
            f"Failed to notify owner after hold ({message!r}): {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    raise SystemExit(0)


def is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_invoice(invoice: Any, index: int, seen_ids: set[str]) -> str | None:
    if not isinstance(invoice, dict):
        return f"invoice at index {index} is {type(invoice).__name__}, not an object"

    keys = set(invoice)
    if keys != EXPECTED_INVOICE_FIELDS:
        missing = sorted(EXPECTED_INVOICE_FIELDS - keys)
        unexpected = sorted(keys - EXPECTED_INVOICE_FIELDS)
        return (
            f"invoice at index {index} has schema mismatch; "
            f"missing={missing}, unexpected={unexpected}"
        )

    invoice_id = invoice["id"]
    if not isinstance(invoice_id, str) or not invoice_id:
        return f"invoice at index {index} has a non-empty-string id requirement violation"
    if invoice_id in seen_ids:
        return f"invoice id {invoice_id!r} is duplicated"

    if not isinstance(invoice["vendor"], str):
        return f"invoice {invoice_id!r} has non-string vendor"
    if not is_plain_int(invoice["amount_cents"]):
        return f"invoice {invoice_id!r} has non-integer amount_cents"
    if invoice["currency"] != "EUR":
        return f"invoice {invoice_id!r} has unexpected currency {invoice['currency']!r}"
    if not is_plain_int(invoice["days_overdue"]):
        return f"invoice {invoice_id!r} has non-integer days_overdue"
    if not isinstance(invoice["contact_email"], str) or not invoice["contact_email"]:
        return f"invoice {invoice_id!r} has missing or non-string contact_email"

    seen_ids.add(invoice_id)
    return None


def main() -> None:
    try:
        last_report = request_json("GET", "/reports/last")
    except Exception as exc:
        hold(f"could not read the last reported week: {type(exc).__name__}: {exc}")

    if not isinstance(last_report, dict) or set(last_report) != {"last_week"}:
        hold(f"/reports/last returned an unexpected object: {last_report!r}")
    last_week = last_report["last_week"]
    if not is_plain_int(last_week) or last_week < 0:
        hold(f"/reports/last returned invalid last_week={last_week!r}")
    week = last_week + 1

    try:
        invoices = request_json("GET", f"/invoices?week={week}")
    except Exception as exc:
        hold(f"could not read invoices for week {week}: {type(exc).__name__}: {exc}")

    if not isinstance(invoices, list):
        hold(f"week {week} invoices response was {type(invoices).__name__}, not a list")

    seen_ids: set[str] = set()
    for index, invoice in enumerate(invoices):
        problem = validate_invoice(invoice, index, seen_ids)
        if problem is not None:
            hold(f"week {week}: {problem}; no reminders or digest were posted")

    total_amount_cents = sum(invoice["amount_cents"] for invoice in invoices)
    reminders_sent = 0
    for invoice in invoices:
        try:
            request_json(
                "POST",
                "/remind",
                {"to": invoice["contact_email"], "invoice_id": invoice["id"]},
            )
        except Exception as exc:
            hold(
                f"week {week}: reminder for invoice {invoice['id']!r} had an uncertain "
                f"outcome after {reminders_sent} confirmed reminders; no digest was posted: "
                f"{type(exc).__name__}: {exc}"
            )
        reminders_sent += 1

    digest = {
        "week": week,
        "invoice_count": len(seen_ids),
        "total_amount_cents": total_amount_cents,
        "reminders_sent": reminders_sent,
        "flagged_invoice_ids": [],
    }
    try:
        request_json("POST", "/report", digest)
    except Exception as exc:
        hold(
            f"week {week}: digest delivery had an uncertain outcome after "
            f"{reminders_sent} reminders: {type(exc).__name__}: {exc}"
        )


if __name__ == "__main__":
    main()
