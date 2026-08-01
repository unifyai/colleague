#!/usr/bin/env python3
"""Aggregate and submit the next batch of unprocessed orders."""

import json
import urllib.request

BASE_URL = "http://127.0.0.1:8125"


def get_json(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30) as response:
        return json.load(response)


def main():
    last_seq = get_json("/batches/last")["last_seq"]

    while orders := get_json(f"/orders?after={last_seq}"):
        revenue_by_region = {}
        total_units = 0
        total_revenue = 0

        for order in orders:
            revenue = order["units"] * order["unit_price_minor"]
            total_units += order["units"]
            total_revenue += revenue
            region = order["region"]
            revenue_by_region[region] = revenue_by_region.get(region, 0) + revenue

        batch = {
            "batch_start_seq": orders[0]["seq"],
            "batch_end_seq": orders[-1]["seq"],
            "order_count": len(orders),
            "total_units": total_units,
            "total_revenue_cents": total_revenue,
            "revenue_by_region_cents": revenue_by_region,
        }
        request = urllib.request.Request(
            f"{BASE_URL}/batches",
            data=json.dumps(batch, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            pass
        last_seq = orders[-1]["seq"]


if __name__ == "__main__":
    main()
