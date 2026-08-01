#!/usr/bin/env python3

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "http://127.0.0.1:8123"


def get_orders(start, end):
    query = urlencode({"start": start.isoformat(), "end": end.isoformat()})
    with urlopen(f"{API_BASE}/orders?{query}", timeout=30) as response:
        orders = json.load(response)

    if not isinstance(orders, list):
        raise ValueError("orders response must be a JSON list")
    return orders


def revenue_for_week(orders, start, end):
    total_units = 0
    total_revenue_cents = 0
    revenue_by_region_cents = defaultdict(int)

    for order in orders:
        order_date = datetime.strptime(order["date"], "%Y-%m-%d").date()
        if not start <= order_date <= end:
            continue

        units = int(order["units"])
        unit_price_cents = int(order["unit_price_cents"])
        revenue = units * unit_price_cents
        total_units += units
        total_revenue_cents += revenue
        revenue_by_region_cents[str(order["region"])] += revenue

    return total_units, total_revenue_cents, dict(revenue_by_region_cents)


def main():
    run_date = datetime.now(timezone.utc).date()
    current_week_start = run_date - timedelta(days=run_date.weekday())
    week_start = current_week_start - timedelta(days=7)
    week_end = week_start + timedelta(days=6)
    previous_week_start = week_start - timedelta(days=7)
    previous_week_end = week_start - timedelta(days=1)

    current_orders = get_orders(week_start, week_end)
    previous_orders = get_orders(previous_week_start, previous_week_end)
    total_units, total_revenue_cents, revenue_by_region_cents = revenue_for_week(
        current_orders,
        week_start,
        week_end,
    )
    _, previous_revenue_cents, _ = revenue_for_week(
        previous_orders,
        previous_week_start,
        previous_week_end,
    )
    if previous_revenue_cents == 0:
        raise ValueError("cannot compute week-over-week change from zero revenue")

    report = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_units": total_units,
        "total_revenue_cents": total_revenue_cents,
        "revenue_by_region_cents": revenue_by_region_cents,
        "wow_revenue_change_pct": round(
            (total_revenue_cents - previous_revenue_cents)
            / previous_revenue_cents
            * 100,
            2,
        ),
    }
    request = Request(
        f"{API_BASE}/report",
        data=json.dumps(report).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"report delivery failed with HTTP {response.status}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"weekly orders report failed: {error}", file=sys.stderr)
        raise
