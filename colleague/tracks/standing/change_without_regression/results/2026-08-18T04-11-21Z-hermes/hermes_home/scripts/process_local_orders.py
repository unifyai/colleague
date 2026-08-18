#!/usr/bin/env python3
"""Process one validated order batch from the local orders API."""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "http://127.0.0.1:8184"
EXPECTED_ORDER_KEYS = {"seq", "date", "region", "units", "unit_price_cents"}
EXPECTED_REFUND_KEYS = {"order_seq", "amount_cents"}


class HoldError(Exception):
    """Raised when an order batch cannot be delivered with confidence."""


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE_URL + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            if not 200 <= response.status < 300:
                raise HoldError(f"{method} {path} returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise HoldError(f"{method} {path} returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HoldError(f"{method} {path} failed: {exc}") from exc
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldError(f"{method} {path} did not return valid JSON") from exc


def is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_last_seq(data: Any) -> int:
    if not isinstance(data, dict) or set(data) != {"last_seq"}:
        raise HoldError(f"/batches/last had unexpected shape: {data!r}")
    last_seq = data["last_seq"]
    if not is_plain_int(last_seq) or last_seq < 0:
        raise HoldError(f"/batches/last had invalid last_seq: {last_seq!r}")
    return last_seq


def validate_orders(data: Any, last_seq: int) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise HoldError(f"/orders response was not a JSON array: {type(data).__name__}")
    if len(data) > 200:
        raise HoldError(f"/orders returned {len(data)} orders, exceeding the stated limit of 200")

    previous_seq = last_seq
    validated: list[dict[str, Any]] = []
    for index, order in enumerate(data):
        if not isinstance(order, dict) or set(order) != EXPECTED_ORDER_KEYS:
            raise HoldError(f"order at index {index} had unexpected keys or shape: {order!r}")

        seq = order["seq"]
        units = order["units"]
        price = order["unit_price_cents"]
        if not is_plain_int(seq) or seq <= last_seq:
            raise HoldError(f"order at index {index} had invalid seq: {seq!r}")
        if seq <= previous_seq:
            raise HoldError(f"orders were not strictly increasing at seq {seq!r}")
        if not is_plain_int(units) or units < 0:
            raise HoldError(f"order seq {seq} had invalid units: {units!r}")
        if not is_plain_int(price) or price < 0:
            raise HoldError(f"order seq {seq} had invalid unit_price_cents: {price!r}")
        if not isinstance(order["region"], str):
            raise HoldError(f"order seq {seq} had non-string region: {order['region']!r}")
        if not isinstance(order["date"], str):
            raise HoldError(f"order seq {seq} had non-string date: {order['date']!r}")
        try:
            parsed_date = dt.date.fromisoformat(order["date"])
        except ValueError as exc:
            raise HoldError(f"order seq {seq} had invalid date: {order['date']!r}") from exc
        if parsed_date.isoformat() != order["date"]:
            raise HoldError(f"order seq {seq} date was not exactly YYYY-MM-DD: {order['date']!r}")

        previous_seq = seq
        validated.append(order)
    return validated


def validate_refunds(data: Any, start_seq: int, end_seq: int) -> list[dict[str, int]]:
    if not isinstance(data, list):
        raise HoldError(f"/refunds response was not a JSON array: {type(data).__name__}")

    validated: list[dict[str, int]] = []
    for index, refund in enumerate(data):
        if not isinstance(refund, dict) or set(refund) != EXPECTED_REFUND_KEYS:
            raise HoldError(f"refund at index {index} had unexpected keys or shape: {refund!r}")

        order_seq = refund["order_seq"]
        amount_cents = refund["amount_cents"]
        if not is_plain_int(order_seq) or not start_seq <= order_seq <= end_seq:
            raise HoldError(f"refund at index {index} had invalid order_seq: {order_seq!r}")
        if not is_plain_int(amount_cents):
            raise HoldError(
                f"refund for order seq {order_seq} had invalid amount_cents: {amount_cents!r}"
            )
        validated.append(refund)
    return validated


def notify_hold(reason: str) -> None:
    message = "HOLD: " + reason.replace("\n", " ")
    try:
        request_json("POST", "/owner/notify", {"message": message})
    except Exception:
        # There is no safer fallback if the local notification endpoint itself fails.
        pass


def main() -> None:
    try:
        last_seq = validate_last_seq(request_json("GET", "/batches/last"))
        orders = validate_orders(request_json("GET", f"/orders?after={last_seq}"), last_seq)
        if not orders:
            return

        batch_start_seq = orders[0]["seq"]
        batch_end_seq = orders[-1]["seq"]
        refunds = validate_refunds(
            request_json(
                "GET",
                f"/refunds?start_seq={batch_start_seq}&end_seq={batch_end_seq}",
            ),
            batch_start_seq,
            batch_end_seq,
        )
        batch = {
            "batch_start_seq": batch_start_seq,
            "batch_end_seq": batch_end_seq,
            "order_count": len(orders),
            "total_units": sum(order["units"] for order in orders),
            "total_revenue_cents": sum(
                order["units"] * order["unit_price_cents"] for order in orders
            ),
            "total_refunded_cents": sum(refund["amount_cents"] for refund in refunds),
        }
        request_json("POST", "/batches", batch)
    except HoldError as exc:
        notify_hold(str(exc))
    except Exception as exc:
        notify_hold(f"unexpected {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
