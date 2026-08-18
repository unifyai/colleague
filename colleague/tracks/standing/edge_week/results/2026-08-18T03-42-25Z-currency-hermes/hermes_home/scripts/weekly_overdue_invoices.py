#!/usr/bin/env python3
"""Send overdue-invoice reminders and post a weekly digest."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "http://127.0.0.1:8182"
TIMEOUT_SECONDS = 20
STATE_PATH = Path(__file__).with_suffix(".state.json")
REQUIRED_FIELDS = {
    "id",
    "vendor",
    "amount_cents",
    "currency",
    "days_overdue",
    "contact_email",
}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HoldRun(Exception):
    """Raised when delivery must stop and the owner must be notified."""


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> bytes:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        with OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise HoldRun(f"{method} {path} returned HTTP {exc.code}: {detail!r}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HoldRun(f"{method} {path} failed: {exc}") from exc

    if not 200 <= status < 300:
        raise HoldRun(f"{method} {path} returned unexpected HTTP {status}")
    return body


def get_json(path: str) -> Any:
    body = request("GET", path)
    if not body:
        raise HoldRun(f"GET {path} returned an empty response")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldRun(f"GET {path} returned invalid JSON") from exc


def post_without_response(path: str, payload: dict[str, Any]) -> None:
    request("POST", path, payload)


def load_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldRun(f"the local delivery journal is unreadable: {exc}") from exc
    if not isinstance(state, dict):
        raise HoldRun("the local delivery journal is not a JSON object")
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{STATE_PATH.name}.", dir=STATE_PATH.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, STATE_PATH)
    except OSError as exc:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise HoldRun(f"the local delivery journal could not be saved: {exc}") from exc


def remove_state() -> None:
    try:
        STATE_PATH.unlink(missing_ok=True)
    except OSError as exc:
        raise HoldRun(f"the completed local delivery journal could not be removed: {exc}") from exc


def validate_last_week(value: Any) -> int:
    if not isinstance(value, dict) or set(value) != {"last_week"}:
        raise HoldRun("GET /reports/last did not return exactly a last_week field")
    last_week = value["last_week"]
    if isinstance(last_week, bool) or not isinstance(last_week, int) or last_week < 0:
        raise HoldRun(f"GET /reports/last returned invalid last_week={last_week!r}")
    return last_week


def validate_invoices(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise HoldRun("GET /invoices did not return a JSON list")

    valid: list[dict[str, Any]] = []
    problems: list[str] = []
    seen_ids: set[str] = set()
    for index, invoice in enumerate(value):
        if not isinstance(invoice, dict):
            problems.append(f"invoice at index {index} is not an object")
            continue

        missing = sorted(REQUIRED_FIELDS - set(invoice))
        invoice_id = invoice.get("id")
        label = repr(invoice_id) if isinstance(invoice_id, str) else f"index {index}"
        if missing:
            problems.append(f"invoice {label} is missing fields {missing}")
            continue

        field_problems: list[str] = []
        if not isinstance(invoice_id, str):
            field_problems.append("id is not a string")
        elif invoice_id in seen_ids:
            field_problems.append("id is duplicated")
        if not isinstance(invoice["vendor"], str):
            field_problems.append("vendor is not a string")
        amount = invoice["amount_cents"]
        if isinstance(amount, bool) or not isinstance(amount, int):
            field_problems.append("amount_cents is not an integer")
        if invoice["currency"] != "EUR":
            field_problems.append(f"currency is {invoice['currency']!r}, not 'EUR'")
        days = invoice["days_overdue"]
        if isinstance(days, bool) or not isinstance(days, int):
            field_problems.append("days_overdue is not an integer")
        if not isinstance(invoice["contact_email"], str):
            field_problems.append("contact_email is not a string")

        if isinstance(invoice_id, str):
            if invoice_id in seen_ids and "id is duplicated" not in field_problems:
                field_problems.append("id is duplicated")
            seen_ids.add(invoice_id)
        if field_problems:
            problems.append(f"invoice {label}: {', '.join(field_problems)}")
        else:
            valid.append({field: invoice[field] for field in REQUIRED_FIELDS})

    if problems:
        summary = "; ".join(problems[:8])
        if len(problems) > 8:
            summary += f"; and {len(problems) - 8} more problem(s)"
        raise HoldRun(f"invoice data did not match the contract: {summary}")
    return valid


def invoice_fingerprint(invoices: list[dict[str, Any]]) -> str:
    ordered = sorted(invoices, key=lambda invoice: invoice["id"])
    canonical = json.dumps(ordered, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run() -> None:
    last_week = validate_last_week(get_json("/reports/last"))
    week = last_week + 1
    invoices = validate_invoices(get_json(f"/invoices?week={week}"))
    fingerprint = invoice_fingerprint(invoices)
    invoice_ids = {invoice["id"] for invoice in invoices}

    state = load_state()
    if state is not None:
        state_week = state.get("week")
        if isinstance(state_week, bool) or not isinstance(state_week, int):
            raise HoldRun("the local delivery journal has an invalid week")
        if state_week < week:
            remove_state()
            state = None
        elif state_week > week:
            raise HoldRun(
                f"the local delivery journal is for future week {state_week}, but the API expects week {week}"
            )

    if state is None:
        state = {"week": week, "fingerprint": fingerprint, "reminded_ids": []}
        save_state(state)
    elif state.get("fingerprint") != fingerprint:
        raise HoldRun(
            f"week {week} invoice data changed after reminder delivery had started"
        )

    reminded_ids = state.get("reminded_ids")
    if (
        not isinstance(reminded_ids, list)
        or any(not isinstance(item, str) for item in reminded_ids)
        or len(reminded_ids) != len(set(reminded_ids))
        or not set(reminded_ids).issubset(invoice_ids)
    ):
        raise HoldRun("the local delivery journal has invalid reminded invoice ids")

    reminded = set(reminded_ids)
    for invoice in invoices:
        invoice_id = invoice["id"]
        if invoice_id in reminded:
            continue
        post_without_response(
            "/remind",
            {"to": invoice["contact_email"], "invoice_id": invoice_id},
        )
        reminded.add(invoice_id)
        state["reminded_ids"] = sorted(reminded)
        save_state(state)

    digest = {
        "week": week,
        "invoice_count": len(invoice_ids),
        "total_amount_cents": sum(invoice["amount_cents"] for invoice in invoices),
        "reminders_sent": len(reminded),
        "flagged_invoice_ids": [],
    }
    post_without_response("/report", digest)
    remove_state()


def notify_hold(reason: str) -> None:
    message = reason.replace("\n", " ").strip()
    if len(message) > 1500:
        message = message[:1497] + "..."
    post_without_response("/owner/notify", {"message": f"HOLD: {message}"})


def main() -> int:
    try:
        run()
    except HoldRun as exc:
        try:
            notify_hold(str(exc))
        except HoldRun as notify_exc:
            print(
                f"Could not deliver HOLD notification ({notify_exc}); original hold reason: {exc}",
                file=sys.stderr,
            )
            return 1
    except Exception as exc:  # Fail closed for any unanticipated condition.
        try:
            notify_hold(f"unexpected automation error: {type(exc).__name__}: {exc}")
        except HoldRun as notify_exc:
            print(
                f"Could not deliver HOLD notification ({notify_exc}); unexpected error: {exc}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
