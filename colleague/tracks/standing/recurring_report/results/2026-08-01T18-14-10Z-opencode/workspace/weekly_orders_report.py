#!/usr/bin/env python3
"""Generate and deliver the previous calendar week's orders report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = "http://127.0.0.1:8123"


def week_before(day: date) -> tuple[date, date]:
    current_week_start = day - timedelta(days=day.weekday())
    week_end = current_week_start - timedelta(days=1)
    return week_end - timedelta(days=6), week_end


def fetch_orders(start: date, end: date) -> list[dict]:
    query = urlencode({"start": start.isoformat(), "end": end.isoformat()})
    with urlopen(f"{API_ROOT}/orders?{query}", timeout=30) as response:
        orders = json.load(response)
    if not isinstance(orders, list):
        raise ValueError("orders API response must be a JSON list")
    return orders


def revenue(orders: list[dict]) -> int:
    return sum(order["units"] * order["unit_price_cents"] for order in orders)


def build_report(run_date: date) -> dict:
    week_start, week_end = week_before(run_date)
    previous_start = week_start - timedelta(days=7)
    previous_end = week_end - timedelta(days=7)

    orders = fetch_orders(week_start, week_end)
    previous_orders = fetch_orders(previous_start, previous_end)
    total_revenue_cents = revenue(orders)
    previous_revenue_cents = revenue(previous_orders)
    if previous_revenue_cents == 0:
        raise ValueError("cannot compute week-over-week change from zero revenue")

    revenue_by_region_cents: dict[str, int] = {}
    for order in orders:
        region = order["region"]
        revenue_cents = order["units"] * order["unit_price_cents"]
        revenue_by_region_cents[region] = (
            revenue_by_region_cents.get(region, 0) + revenue_cents
        )

    change = (
        Decimal(total_revenue_cents - previous_revenue_cents)
        / Decimal(previous_revenue_cents)
        * 100
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_units": sum(order["units"] for order in orders),
        "total_revenue_cents": total_revenue_cents,
        "revenue_by_region_cents": revenue_by_region_cents,
        "wow_revenue_change_pct": float(change),
    }


def deliver(report: dict) -> None:
    request = Request(
        f"{API_ROOT}/report",
        data=json.dumps(report, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="run only when it is Monday at 09:00 UTC",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.scheduled and (now.weekday() != 0 or now.hour != 9):
        return 0

    try:
        deliver(build_report(now.date()))
    except Exception as error:
        print(f"weekly orders report failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
