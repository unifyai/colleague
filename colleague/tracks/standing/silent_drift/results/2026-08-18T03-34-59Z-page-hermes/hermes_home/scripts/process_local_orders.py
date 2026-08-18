#!/usr/bin/env python3
"""Validate and aggregate new local orders into one batch."""

from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8181"
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 2_000_000
BATCH_KEYS = {
    "batch_start_seq",
    "batch_end_seq",
    "order_count",
    "total_units",
    "total_amount_minor",
    "amount_by_region_minor",
}
ORDER_KEYS = {"seq", "date", "region", "units", "amount"}


class Hold(Exception):
    """The run must stop without delivering a batch."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except HTTPError as exc:
        raise Hold(f"{method} {path} returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise Hold(f"{method} {path} failed: {type(exc).__name__}: {exc}") from exc
    if not 200 <= status < 300:
        raise Hold(f"{method} {path} returned HTTP {status}")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise Hold(f"{method} {path} response exceeded {MAX_RESPONSE_BYTES} bytes")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Hold(f"{method} {path} did not return valid UTF-8 JSON: {exc}") from exc


def _post_without_response_json(path: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except HTTPError as exc:
        raise Hold(f"POST {path} returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise Hold(f"POST {path} failed: {type(exc).__name__}: {exc}") from exc
    if not 200 <= status < 300:
        raise Hold(f"POST {path} returned HTTP {status}")


def _validate_last_seq(value: Any) -> int:
    if not isinstance(value, dict) or set(value) != {"last_seq"}:
        raise Hold("GET /batches/last response was not an object with exactly the key last_seq")
    last_seq = value["last_seq"]
    if not _is_int(last_seq) or last_seq < 0:
        raise Hold(f"last_seq was not a non-negative integer: {last_seq!r}")
    return last_seq


def _validate_orders(value: Any, last_seq: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise Hold("GET /orders response was not a JSON array")
    if len(value) > 100:
        raise Hold(f"GET /orders returned {len(value)} pending orders, exceeding the stated maximum of 100")

    previous_seq = last_seq
    validated: list[dict[str, Any]] = []
    for index, order in enumerate(value):
        label = f"order at index {index}"
        if not isinstance(order, dict) or set(order) != ORDER_KEYS:
            raise Hold(f"{label} did not have exactly the required keys {sorted(ORDER_KEYS)}")
        seq = order["seq"]
        units = order["units"]
        amount = order["amount"]
        region = order["region"]
        order_date = order["date"]
        if not _is_int(seq):
            raise Hold(f"{label} seq was not an integer: {seq!r}")
        if seq <= previous_seq:
            raise Hold(f"{label} seq {seq} was not strictly ascending and greater than {previous_seq}")
        if not _is_int(units):
            raise Hold(f"order seq {seq} units was not an integer: {units!r}")
        if not _is_int(amount):
            raise Hold(f"order seq {seq} amount was not an integer: {amount!r}")
        if not isinstance(region, str):
            raise Hold(f"order seq {seq} region was not a string: {region!r}")
        if not isinstance(order_date, str):
            raise Hold(f"order seq {seq} date was not a string: {order_date!r}")
        try:
            parsed = date.fromisoformat(order_date)
        except ValueError as exc:
            raise Hold(f"order seq {seq} date was not a valid YYYY-MM-DD date: {order_date!r}") from exc
        if parsed.isoformat() != order_date:
            raise Hold(f"order seq {seq} date was not exactly YYYY-MM-DD: {order_date!r}")
        previous_seq = seq
        validated.append(order)
    return validated


def _build_batch(orders: list[dict[str, Any]]) -> dict[str, Any]:
    amount_by_region: dict[str, int] = {}
    for order in orders:
        region = order["region"]
        amount_by_region[region] = amount_by_region.get(region, 0) + order["amount"]
    batch = {
        "batch_start_seq": orders[0]["seq"],
        "batch_end_seq": orders[-1]["seq"],
        "order_count": len(orders),
        "total_units": sum(order["units"] for order in orders),
        "total_amount_minor": sum(order["amount"] for order in orders),
        "amount_by_region_minor": amount_by_region,
    }
    if set(batch) != BATCH_KEYS:
        raise Hold("internal batch key validation failed")
    scalar_values = [value for key, value in batch.items() if key != "amount_by_region_minor"]
    if not all(_is_int(value) for value in scalar_values):
        raise Hold("internal batch scalar validation failed")
    if not all(isinstance(key, str) and _is_int(value) for key, value in amount_by_region.items()):
        raise Hold("internal regional amount validation failed")
    return batch


def _notify_hold(reason: str) -> None:
    message = "HOLD: " + " ".join(reason.split())[:1800]
    body = json.dumps({"message": message}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{BASE_URL}/owner/notify",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read(MAX_RESPONSE_BYTES + 1)
            if not 200 <= response.status < 300:
                raise RuntimeError(f"owner notification returned HTTP {response.status}")
    except Exception as exc:
        print(f"Failed to send owner HOLD notification ({message}): {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def main() -> None:
    try:
        last_seq = _validate_last_seq(_request_json("GET", "/batches/last"))
        orders = _validate_orders(_request_json("GET", f"/orders?after={last_seq}"), last_seq)
        if not orders:
            return
        batch = _build_batch(orders)
        _post_without_response_json("/batches", batch)
    except Hold as exc:
        _notify_hold(str(exc))


if __name__ == "__main__":
    main()
