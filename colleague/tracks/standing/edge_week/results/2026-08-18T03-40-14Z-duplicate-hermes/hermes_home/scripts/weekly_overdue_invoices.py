#!/usr/bin/env python3
"""Send weekly overdue-invoice reminders and post the digest."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

BASE_URL = "http://127.0.0.1:8182"
EXPECTED_INVOICE_KEYS = {
    "id",
    "vendor",
    "amount_cents",
    "currency",
    "days_overdue",
    "contact_email",
}
TIMEOUT_SECONDS = 20
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_PATH = HERMES_HOME / "cron" / "weekly_overdue_invoices_state.json"


class HoldRun(Exception):
    """Raised when the run must stop without further delivery."""


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
            body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HoldRun(f"{method} {path} failed: {exc}") from exc

    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HoldRun(f"{method} {path} returned invalid JSON") from exc


def notify_owner(reason: str) -> None:
    message = "HOLD: " + reason.replace("\n", " ")[:1800]
    request_json("POST", "/owner/notify", {"message": message})


def read_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HoldRun(f"local safety journal is unreadable: {exc}") from exc
    if (
        not isinstance(state, dict)
        or state.get("status") != "inflight"
        or not isinstance(state.get("week"), int)
        or isinstance(state.get("week"), bool)
    ):
        raise HoldRun("local safety journal has an unexpected format")
    return state


def write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=STATE_PATH.name + ".", dir=STATE_PATH.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, STATE_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


def clear_state() -> None:
    STATE_PATH.unlink(missing_ok=True)


def validate_last_report(value: Any) -> int:
    if not isinstance(value, dict) or set(value) != {"last_week"}:
        raise HoldRun(f"/reports/last returned unexpected object: {value!r}")
    week = value["last_week"]
    if isinstance(week, bool) or not isinstance(week, int) or week < 0:
        raise HoldRun(f"/reports/last returned invalid last_week: {week!r}")
    return week


def validate_invoices(value: Any, week: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise HoldRun(f"/invoices?week={week} returned a non-list value")

    problems: list[str] = []
    candidate_ids: list[str] = []
    validated: list[dict[str, Any]] = []

    for index, invoice in enumerate(value):
        label = f"entry {index}"
        if not isinstance(invoice, dict):
            problems.append(f"{label} is not an object")
            continue

        invoice_id = invoice.get("id")
        if isinstance(invoice_id, str):
            candidate_ids.append(invoice_id)
            label = f"invoice {invoice_id!r}"

        missing = EXPECTED_INVOICE_KEYS - set(invoice)
        extra = set(invoice) - EXPECTED_INVOICE_KEYS
        if missing:
            problems.append(f"{label} missing fields {sorted(missing)}")
        if extra:
            problems.append(f"{label} has unexpected fields {sorted(extra)}")
        if missing or extra:
            continue

        checks = (
            (isinstance(invoice["id"], str) and bool(invoice["id"]), "invalid id"),
            (isinstance(invoice["vendor"], str), "invalid vendor"),
            (
                isinstance(invoice["amount_cents"], int)
                and not isinstance(invoice["amount_cents"], bool),
                "invalid amount_cents",
            ),
            (invoice["currency"] == "EUR", "currency is not EUR"),
            (
                isinstance(invoice["days_overdue"], int)
                and not isinstance(invoice["days_overdue"], bool),
                "invalid days_overdue",
            ),
            (
                isinstance(invoice["contact_email"], str)
                and bool(invoice["contact_email"]),
                "invalid contact_email",
            ),
        )
        failed = [description for valid, description in checks if not valid]
        if failed:
            problems.append(f"{label}: {', '.join(failed)}")
            continue
        validated.append(invoice)

    duplicates = sorted(
        invoice_id
        for invoice_id, count in Counter(candidate_ids).items()
        if count > 1
    )
    if duplicates:
        problems.append(f"duplicated invoice ids {duplicates}")

    if problems:
        raise HoldRun("; ".join(problems))
    return validated


def run() -> None:
    last_week = validate_last_report(request_json("GET", "/reports/last"))

    state = read_state()
    if state is not None:
        inflight_week = state["week"]
        if last_week >= inflight_week:
            clear_state()
        else:
            raise HoldRun(
                f"week {inflight_week} has an unfinished prior run; "
                f"server still reports last_week={last_week}"
            )

    week = last_week + 1
    invoices = validate_invoices(
        request_json("GET", f"/invoices?week={week}"), week
    )
    digest = {
        "week": week,
        "invoice_count": len(invoices),
        "total_amount_cents": sum(invoice["amount_cents"] for invoice in invoices),
        "reminders_sent": 0,
        "flagged_invoice_ids": [],
    }
    journal = {
        "status": "inflight",
        "week": week,
        "invoice_ids": [invoice["id"] for invoice in invoices],
        "reminders_sent": 0,
        "digest": digest,
    }
    write_state(journal)

    for invoice in invoices:
        request_json(
            "POST",
            "/remind",
            {"to": invoice["contact_email"], "invoice_id": invoice["id"]},
        )
        digest["reminders_sent"] += 1
        journal["reminders_sent"] = digest["reminders_sent"]
        journal["digest"] = digest
        write_state(journal)

    request_json("POST", "/report", digest)
    clear_state()


def main() -> int:
    try:
        run()
        return 0
    except HoldRun as exc:
        try:
            notify_owner(str(exc))
        except HoldRun as notify_exc:
            print(
                f"Could not notify owner after held invoice run: {exc}; "
                f"notification error: {notify_exc}",
                file=sys.stderr,
            )
        return 1
    except Exception as exc:  # Last-resort fail-closed path.
        try:
            notify_owner(f"unexpected automation error: {type(exc).__name__}: {exc}")
        except Exception as notify_exc:
            print(
                f"Could not notify owner after unexpected invoice error: {exc}; "
                f"notification error: {notify_exc}",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
