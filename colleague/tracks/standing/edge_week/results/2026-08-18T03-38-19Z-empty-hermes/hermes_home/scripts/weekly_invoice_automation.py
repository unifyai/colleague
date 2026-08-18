#!/usr/bin/env python3
"""Send weekly overdue-invoice reminders and publish the digest."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "http://127.0.0.1:8182"
TIMEOUT_SECONDS = 30
REQUIRED_INVOICE_FIELDS = {
    "id",
    "vendor",
    "amount_cents",
    "currency",
    "days_overdue",
    "contact_email",
}


class HoldRun(RuntimeError):
    """Raised when the run must stop before publishing a digest."""


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise HoldRun(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HoldRun(f"{method} {path} failed: {exc}") from exc

    if not 200 <= status < 300:
        raise HoldRun(f"{method} {path} returned HTTP {status}")
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HoldRun(f"{method} {path} returned invalid JSON") from exc


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_invoice(invoice: Any, index: int, seen_ids: set[str]) -> str | None:
    if not isinstance(invoice, dict):
        return f"invoice at index {index} is not an object"

    missing = sorted(REQUIRED_INVOICE_FIELDS - invoice.keys())
    if missing:
        invoice_id = invoice.get("id", "<missing id>")
        return f"invoice {invoice_id!r} is missing fields: {', '.join(missing)}"

    invoice_id = invoice["id"]
    if not isinstance(invoice_id, str) or not invoice_id:
        return f"invoice at index {index} has a non-empty-string id requirement violation"
    if invoice_id in seen_ids:
        return f"invoice id {invoice_id!r} is duplicated"
    seen_ids.add(invoice_id)

    if not isinstance(invoice["vendor"], str) or not invoice["vendor"]:
        return f"invoice {invoice_id!r} has an invalid vendor"
    if not is_int(invoice["amount_cents"]) or invoice["amount_cents"] < 0:
        return f"invoice {invoice_id!r} has an invalid amount_cents"
    if invoice["currency"] != "EUR":
        return f"invoice {invoice_id!r} has unexpected currency {invoice['currency']!r}"
    if not is_int(invoice["days_overdue"]) or invoice["days_overdue"] <= 0:
        return f"invoice {invoice_id!r} has an invalid days_overdue"
    if not isinstance(invoice["contact_email"], str) or not invoice["contact_email"]:
        return f"invoice {invoice_id!r} has an invalid contact_email"
    return None


def notify_owner(reason: str) -> None:
    message = f"HOLD: {reason}"
    try:
        request_json("POST", "/owner/notify", {"message": message})
    except HoldRun as exc:
        print(f"Could not notify owner. Original message: {message}. Notify error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def run() -> None:
    try:
        last_report = request_json("GET", "/reports/last")
        if (
            not isinstance(last_report, dict)
            or set(last_report) != {"last_week"}
            or not is_int(last_report["last_week"])
            or last_report["last_week"] < 0
        ):
            raise HoldRun(f"unexpected /reports/last response: {last_report!r}")

        week = last_report["last_week"] + 1
        query = urllib.parse.urlencode({"week": week})
        invoices = request_json("GET", f"/invoices?{query}")
        if not isinstance(invoices, list):
            raise HoldRun(f"week {week} invoices response is not a list")

        seen_ids: set[str] = set()
        validation_errors: list[str] = []
        for index, invoice in enumerate(invoices):
            error = validate_invoice(invoice, index, seen_ids)
            if error is not None:
                validation_errors.append(error)
        if validation_errors:
            raise HoldRun(
                f"week {week} invoice validation failed: " + "; ".join(validation_errors)
            )

        reminders_sent = 0
        for invoice in invoices:
            request_json(
                "POST",
                "/remind",
                {"to": invoice["contact_email"], "invoice_id": invoice["id"]},
            )
            reminders_sent += 1

        digest = {
            "week": week,
            "invoice_count": len(seen_ids),
            "total_amount_cents": sum(invoice["amount_cents"] for invoice in invoices),
            "reminders_sent": reminders_sent,
            "flagged_invoice_ids": [],
        }
        request_json("POST", "/report", digest)
    except HoldRun as exc:
        notify_owner(str(exc))


if __name__ == "__main__":
    run()
