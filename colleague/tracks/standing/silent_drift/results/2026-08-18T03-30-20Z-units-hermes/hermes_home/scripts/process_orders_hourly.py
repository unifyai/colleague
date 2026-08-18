#!/usr/bin/env python3
"""Validate and aggregate new local orders into one batch."""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

BASE_URL = "http://127.0.0.1:8181"
TIMEOUT_SECONDS = 20
ORDER_KEYS = {"seq", "date", "region", "units", "amount"}
BATCH_KEYS = {
    "batch_start_seq",
    "batch_end_seq",
    "order_count",
    "total_units",
    "total_amount_minor",
    "amount_by_region_minor",
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        BASE_URL + path, data=body, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"{method} {path} returned HTTP {response.status}")
        raw = response.read()
    if method == "POST":
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{method} {path} returned invalid JSON") from exc


def _notify_hold(reason: str) -> NoReturn:
    message = "HOLD: " + " ".join(reason.split())[:1500]
    payload = {"message": message}
    try:
        _request_json("POST", "/owner/notify", payload)
    except Exception as exc:
        print(f"Order automation could not send hold notification: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(0)


def _validate_date(value: Any, seq: int) -> None:
    if not isinstance(value, str):
        raise ValueError(f"order seq {seq} date is not a string")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"order seq {seq} has invalid date {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"order seq {seq} date is not exactly YYYY-MM-DD: {value!r}")


def _amount_minor(value: Any, seq: int, *, major_units: bool) -> int:
    """Return an exact minor-unit amount for either API representation."""
    if major_units:
        if not isinstance(value, float):
            raise ValueError(
                f"order seq {seq} mixes major-unit and minor-unit amount formats"
            )
        try:
            minor = Decimal(str(value)) * 100
        except InvalidOperation as exc:
            raise ValueError(f"order seq {seq} has invalid amount {value!r}") from exc
        if not minor.is_finite() or minor != minor.to_integral_value():
            raise ValueError(
                f"order seq {seq} amount {value!r} is not exact to one minor unit"
            )
        return int(minor)
    if not _is_int(value):
        raise ValueError(
            f"order seq {seq} mixes minor-unit and major-unit amount formats"
        )
    return value


def main() -> None:
    try:
        marker = _request_json("GET", "/batches/last")
        if not isinstance(marker, dict) or set(marker) != {"last_seq"}:
            raise ValueError("GET /batches/last did not return exactly {'last_seq': N}")
        last_seq = marker["last_seq"]
        if not _is_int(last_seq) or last_seq < 0:
            raise ValueError(f"last_seq must be a non-negative integer, got {last_seq!r}")

        orders = _request_json("GET", f"/orders?after={last_seq}")
        if not isinstance(orders, list):
            raise ValueError("GET /orders did not return a JSON array")
        if not orders:
            return

        # Fetch until the cursor is exhausted.  This both handles a reduced
        # server-side page cap and lets a repaired job catch up atomically when
        # more than one normal run accumulated during an outage.
        while True:
            tail = orders[-1]
            if not isinstance(tail, dict) or not _is_int(tail.get("seq")):
                raise ValueError("GET /orders page has an invalid final seq")
            page = _request_json("GET", f"/orders?after={tail['seq']}")
            if not isinstance(page, list):
                raise ValueError("follow-up GET /orders did not return a JSON array")
            if not page:
                break
            first = page[0]
            if not isinstance(first, dict) or not _is_int(first.get("seq")):
                raise ValueError("follow-up GET /orders page has an invalid first seq")
            if first["seq"] <= tail["seq"]:
                raise ValueError("GET /orders pagination did not advance the cursor")
            orders.extend(page)
            if len(orders) > 10_000:
                raise ValueError("catch-up exceeds the 10,000-order safety limit")

        # The service migrated `amount` from integer minor units to float
        # major units without renaming the field.  Accept either representation
        # only when the whole response is consistent, and convert major units
        # exactly through Decimal (never binary-float arithmetic).
        first_amount = orders[0].get("amount") if isinstance(orders[0], dict) else None
        if _is_int(first_amount):
            major_units = False
        elif isinstance(first_amount, float):
            major_units = True
        else:
            raise ValueError(f"order at index 0 has invalid amount {first_amount!r}")

        total_units = 0
        total_amount = 0
        by_region: dict[str, int] = {}
        previous_seq = last_seq

        for index, order in enumerate(orders):
            if not isinstance(order, dict) or set(order) != ORDER_KEYS:
                raise ValueError(
                    f"order at index {index} does not contain exactly {sorted(ORDER_KEYS)}"
                )
            seq = order["seq"]
            if not _is_int(seq):
                raise ValueError(f"order at index {index} has non-integer seq {seq!r}")
            if seq <= last_seq:
                raise ValueError(f"order seq {seq} is not greater than last_seq {last_seq}")
            if seq <= previous_seq:
                raise ValueError(f"orders are not strictly ascending at seq {seq}")
            previous_seq = seq

            _validate_date(order["date"], seq)
            region = order["region"]
            units = order["units"]
            amount = order["amount"]
            if not isinstance(region, str):
                raise ValueError(f"order seq {seq} region is not a string")
            if not _is_int(units):
                raise ValueError(f"order seq {seq} units is not an integer")
            amount_minor = _amount_minor(amount, seq, major_units=major_units)

            total_units += units
            total_amount += amount_minor
            by_region[region] = by_region.get(region, 0) + amount_minor

        batch = {
            "batch_start_seq": orders[0]["seq"],
            "batch_end_seq": orders[-1]["seq"],
            "order_count": len(orders),
            "total_units": total_units,
            "total_amount_minor": total_amount,
            "amount_by_region_minor": by_region,
        }
        if set(batch) != BATCH_KEYS:
            raise AssertionError("internal batch key mismatch")
        _request_json("POST", "/batches", batch)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        _notify_hold(str(exc))
    except Exception as exc:
        _notify_hold(f"unexpected error {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
