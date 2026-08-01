#!/usr/bin/env python3

import fcntl
import json
import tempfile
import urllib.request

BASE_URL = "http://127.0.0.1:8125"
TIMEOUT_SECONDS = 30


def get_json(path):
    with urllib.request.urlopen(BASE_URL + path, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


def main():
    # Prevent overlapping cron runs from creating duplicate batches.
    with open(tempfile.gettempdir() + "/process-local-orders.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return

        last_seq = get_json("/batches/last")["last_seq"]
        orders = get_json(f"/orders?after={last_seq}")
        if not orders:
            return

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
            "batch_start_seq": min(order["seq"] for order in orders),
            "batch_end_seq": max(order["seq"] for order in orders),
            "order_count": len(orders),
            "total_units": total_units,
            "total_revenue_cents": total_revenue,
            "revenue_by_region_cents": revenue_by_region,
        }
        request = urllib.request.Request(
            BASE_URL + "/batches",
            data=json.dumps(batch, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
            pass


if __name__ == "__main__":
    main()
