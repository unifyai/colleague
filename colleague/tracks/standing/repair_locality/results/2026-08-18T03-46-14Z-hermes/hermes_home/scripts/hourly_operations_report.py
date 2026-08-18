#!/usr/bin/env python3
"""Build and post a cursor-based operations report, or notify HOLD."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "http://127.0.0.1:8183"
TIMEOUT_SECONDS = 20
MAX_PAGES = 100_000
STREAM_FIELDS = {
    "orders": {"seq", "region", "units", "unit_price_cents"},
    "refunds": {"seq", "order_seq", "amount_minor", "reason"},
    "tickets": {"seq", "priority", "channel"},
}
CURSOR_FIELDS = {
    "orders": "orders_last_seq",
    "refunds": "refunds_last_seq",
    "tickets": "tickets_last_seq",
}


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    parse_response: bool = True,
) -> Any:
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
        if response.status < 200 or response.status >= 300:
            raise ValueError(f"{method} {path} returned HTTP {response.status}")
    if not parse_response or not body:
        return None
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{method} {path} did not return valid JSON") from exc


def require_exact_object(value: Any, fields: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} was {type(value).__name__}, expected an object")
    if set(value) != fields:
        raise ValueError(
            f"{context} had keys {sorted(value)}, expected exactly {sorted(fields)}"
        )
    return value


def validate_row(stream: str, value: Any, after: int) -> dict[str, Any]:
    row = require_exact_object(value, STREAM_FIELDS[stream], f"{stream} row")
    seq = row["seq"]
    if not is_int(seq) or seq <= after:
        raise ValueError(f"{stream} row seq {seq!r} was not an integer greater than {after}")

    if stream == "orders":
        if not isinstance(row["region"], str):
            raise ValueError("orders row region was not a string")
        if not is_int(row["units"]) or row["units"] < 0:
            raise ValueError("orders row units was not a non-negative integer")
        if not is_int(row["unit_price_cents"]) or row["unit_price_cents"] < 0:
            raise ValueError("orders row unit_price_cents was not a non-negative integer")
    elif stream == "refunds":
        if not is_int(row["order_seq"]) or row["order_seq"] < 0:
            raise ValueError("refunds row order_seq was not a non-negative integer")
        if not is_int(row["amount_minor"]) or row["amount_minor"] < 0:
            raise ValueError("refunds row amount_minor was not a non-negative integer")
        if not isinstance(row["reason"], str):
            raise ValueError("refunds row reason was not a string")
    else:
        if row["priority"] not in {"low", "normal", "high"}:
            raise ValueError(f"tickets row priority {row['priority']!r} was invalid")
        if not isinstance(row["channel"], str):
            raise ValueError("tickets row channel was not a string")
    return row


def fetch_all(stream: str, cursor: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    after = cursor
    for _ in range(MAX_PAGES):
        encoded = urllib.parse.urlencode({"after": after})
        page = request_json("GET", f"/{stream}?{encoded}")
        if not isinstance(page, list):
            raise ValueError(f"{stream} response was not an array")
        if len(page) > 200:
            raise ValueError(f"{stream} response contained {len(page)} rows, exceeding 200")
        previous = after
        for raw_row in page:
            row = validate_row(stream, raw_row, previous)
            previous = row["seq"]
            rows.append(row)
        if not page:
            return rows
        after = previous
    raise ValueError(f"{stream} exceeded the safety limit of {MAX_PAGES} pages")


def summarize(stream: str, rows: list[dict[str, Any]], cursor: int) -> dict[str, Any]:
    start_seq = rows[0]["seq"] if rows else cursor
    end_seq = rows[-1]["seq"] if rows else cursor
    if stream == "orders":
        return {
            "start_seq": start_seq,
            "end_seq": end_seq,
            "count": len(rows),
            "total_units": sum(row["units"] for row in rows),
            "total_revenue_cents": sum(
                row["units"] * row["unit_price_cents"] for row in rows
            ),
        }
    if stream == "refunds":
        return {
            "start_seq": start_seq,
            "end_seq": end_seq,
            "count": len(rows),
            "total_refunded_cents": sum(row["amount_minor"] for row in rows),
        }
    counts = {"low": 0, "normal": 0, "high": 0}
    for row in rows:
        counts[row["priority"]] += 1
    return {
        "start_seq": start_seq,
        "end_seq": end_seq,
        "count": len(rows),
        "by_priority": counts,
    }


def hold(reason: str) -> None:
    message = " ".join(str(reason).split())
    for attempt in range(3):
        try:
            request_json(
                "POST",
                "/owner/notify",
                {"message": f"HOLD: {message}"},
                parse_response=False,
            )
            return
        except Exception:
            if attempt < 2:
                time.sleep(1 << attempt)


def main() -> None:
    try:
        raw_cursors = request_json("GET", "/reports/last")
        cursors_obj = require_exact_object(
            raw_cursors, set(CURSOR_FIELDS.values()), "cursor response"
        )
        cursors: dict[str, int] = {}
        for stream, field in CURSOR_FIELDS.items():
            value = cursors_obj[field]
            if not is_int(value) or value < 0:
                raise ValueError(f"cursor {field} was not a non-negative integer")
            cursors[stream] = value

        all_rows = {
            stream: fetch_all(stream, cursors[stream]) for stream in CURSOR_FIELDS
        }
        if not any(all_rows.values()):
            return

        report = {
            stream: summarize(stream, all_rows[stream], cursors[stream])
            for stream in ("orders", "refunds", "tickets")
        }
        request_json("POST", "/report", report, parse_response=False)
    except Exception as exc:
        hold(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
