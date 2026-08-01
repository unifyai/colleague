#!/usr/bin/env python3
"""Generate and POST the previous full UTC week's orders report."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8123"


def fetch_orders(start: str, end: str) -> list[dict]:
    query = urlencode({"start": start, "end": end})
    with urlopen(f"{BASE_URL}/orders?{query}", timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise ValueError("orders API response must be a JSON list")
    return payload


def main() -> None:
    run_time = datetime.now(timezone.utc)
    # The scheduler evaluates cron expressions in the configured Hermes
    # timezone. Run hourly and gate here so delivery is always Monday 09:00
    # UTC, including across local daylight-saving transitions.
    if run_time.weekday() != 0 or run_time.hour != 9:
        return

    run_date = run_time.date()
    current_week_start = run_date - timedelta(days=run_date.weekday())
    week_start_date = current_week_start - timedelta(days=7)
    week_end_date = week_start_date + timedelta(days=6)
    previous_start_date = week_start_date - timedelta(days=7)
    previous_end_date = week_start_date - timedelta(days=1)

    week_start = week_start_date.isoformat()
    week_end = week_end_date.isoformat()
    current_orders = fetch_orders(week_start, week_end)
    previous_orders = fetch_orders(
        previous_start_date.isoformat(),
        previous_end_date.isoformat(),
    )

    total_units = 0
    total_revenue_cents = 0
    revenue_by_region: defaultdict[str, int] = defaultdict(int)

    for order in current_orders:
        if not week_start <= order["date"] <= week_end:
            continue
        units = int(order["units"])
        revenue = units * int(order["unit_price_cents"])
        total_units += units
        total_revenue_cents += revenue
        revenue_by_region[str(order["region"])] += revenue

    previous_revenue_cents = sum(
        int(order["units"]) * int(order["unit_price_cents"])
        for order in previous_orders
        if previous_start_date.isoformat()
        <= order["date"]
        <= previous_end_date.isoformat()
    )
    if previous_revenue_cents == 0:
        raise ZeroDivisionError(
            "cannot compute week-over-week revenue change: previous revenue is zero",
        )

    report = {
        "week_start": week_start,
        "week_end": week_end,
        "total_units": total_units,
        "total_revenue_cents": total_revenue_cents,
        "revenue_by_region_cents": dict(sorted(revenue_by_region.items())),
        "wow_revenue_change_pct": round(
            (total_revenue_cents - previous_revenue_cents)
            / previous_revenue_cents
            * 100,
            2,
        ),
    }
    body = json.dumps(report, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{BASE_URL}/report",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        response.read()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"report API returned HTTP {response.status}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Weekly orders report failed: {exc}", file=sys.stderr)
        raise
