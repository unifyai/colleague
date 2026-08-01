#!/usr/bin/env python3
"""Aggregate the next page of unprocessed orders and post one batch."""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

BASE_URL = "http://127.0.0.1:8127"
TIMEOUT_SECONDS = 30


def get_json(path: str):
    request = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


def post_json(path: str, payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        response.read()


def main() -> int:
    last = get_json("/batches/last")
    last_seq = int(last["last_seq"])
    query = urllib.parse.urlencode({"after": last_seq})
    orders = get_json(f"/orders?{query}")

    if not orders:
        return 0

    revenue_by_region = defaultdict(int)
    total_units = 0
    total_revenue = 0

    for order in orders:
        units = int(order["units"])
        # The orders API exposes monetary values as generic minor units.
        # Keep accepting the former field so queued orders from either API
        # version can be processed during a rolling upgrade.
        unit_price = order.get("unit_price_minor", order.get("unit_price_cents"))
        if unit_price is None:
            raise KeyError("unit_price_minor")
        revenue = units * int(unit_price)
        total_units += units
        total_revenue += revenue
        revenue_by_region[str(order["region"])] += revenue

    payload = {
        "batch_start_seq": int(orders[0]["seq"]),
        "batch_end_seq": int(orders[-1]["seq"]),
        "order_count": len(orders),
        "total_units": total_units,
        "total_revenue_cents": total_revenue,
        "revenue_by_region_cents": dict(revenue_by_region),
    }
    post_json("/batches", payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        KeyError,
        TypeError,
        ValueError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Order batch automation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
