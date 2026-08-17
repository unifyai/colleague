"""Order batches, then a request to add one column — and nothing else moves.

The order stream and batch sink of `drift_recovery`, plus a refunds lookup
by seq range. The report has five columns until the owner asks for a sixth;
after that a correct batch has exactly six, and the first five are byte-for-
byte what they were.

Endpoints:
    GET  /health
    GET  /orders?after=N                        -> orders with seq > N (up to 200)
    GET  /refunds?start_seq=A&end_seq=B         -> refunds against orders in [A, B]
    GET  /batches/last                          -> {"last_seq": ...}
    POST /batches
    GET  /batches
    POST /owner/notify                          -> {"message": ...}
    GET  /owner/messages
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from colleague.harness.fixture_server import FixtureServer, Request
from colleague.tracks.standing.series.spec import install_owner_channel
from colleague.tracks.standing.series.streams import SeqStream, hash_for

DEFAULT_SEED = 20260817
DEFAULT_PORT = 8184
PAGE_LIMIT = 200

REGIONS = ("north", "south", "east", "west")
BASE_PRICE_CENTS = {"north": 1999, "south": 1499, "east": 2499, "west": 999}
STREAM_START_DATE = date(2026, 7, 1)
ORDERS_PER_DAY = 12

OLD_COLUMNS = (
    "batch_start_seq",
    "batch_end_seq",
    "order_count",
    "total_units",
    "total_revenue_cents",
)
NEW_COLUMN = "total_refunded_cents"


def order_for_seq(seed: int, seq: int) -> dict[str, Any]:
    h = hash_for(seed, "order", seq)
    day = STREAM_START_DATE + timedelta(days=(seq - 1) // ORDERS_PER_DAY)
    region = REGIONS[h % len(REGIONS)]
    return {
        "seq": seq,
        "date": day.isoformat(),
        "region": region,
        "units": 1 + (h >> 8) % 19,
        "unit_price_cents": BASE_PRICE_CENTS[region] + ((h >> 16) % 5) * 100,
    }


def refund_for_order(seed: int, order_seq: int) -> dict[str, Any] | None:
    """About one order in four carries a refund; deterministic in (seed, seq)."""
    h = hash_for(seed, "refund", order_seq)
    if h % 4:
        return None
    return {"order_seq": order_seq, "amount_cents": 300 + (h >> 8) % 4000}


def refunds_in_range(seed: int, start_seq: int, end_seq: int) -> list[dict[str, Any]]:
    out = []
    for seq in range(start_seq, end_seq + 1):
        row = refund_for_order(seed, seq)
        if row is not None:
            out.append(row)
    return out


def expected_batch(
    seed: int,
    start_seq: int,
    end_seq: int,
    *,
    with_refunds: bool,
) -> dict[str, Any]:
    orders = [order_for_seq(seed, s) for s in range(start_seq, end_seq + 1)]
    batch: dict[str, Any] = {
        "batch_start_seq": start_seq,
        "batch_end_seq": end_seq,
        "order_count": len(orders),
        "total_units": sum(o["units"] for o in orders),
        "total_revenue_cents": sum(o["units"] * o["unit_price_cents"] for o in orders),
    }
    if with_refunds:
        batch[NEW_COLUMN] = sum(
            r["amount_cents"] for r in refunds_in_range(seed, start_seq, end_seq)
        )
    return batch


def score_batch(
    actual: Any,
    expected: dict[str, Any],
    *,
    with_refunds: bool,
) -> dict[str, Any]:
    """Old columns byte-identical to truth, the new one right, nothing else."""
    if not isinstance(actual, dict):
        return {"exact": False, "checks": {"is_json_object": False}}
    checks: dict[str, bool] = {"is_json_object": True}
    old_identical = True
    for key in OLD_COLUMNS:
        same = key in actual and json.dumps(actual[key]) == json.dumps(expected[key])
        checks[f"old:{key}"] = same
        old_identical = old_identical and same
    checks["old_columns_identical"] = old_identical
    if with_refunds:
        checks["new_column_correct"] = NEW_COLUMN in actual and json.dumps(
            actual[NEW_COLUMN],
        ) == json.dumps(expected[NEW_COLUMN])
    else:
        checks["new_column_absent"] = NEW_COLUMN not in actual
    checks["no_extra_keys"] = not (set(actual) - set(expected))
    return {"exact": all(checks.values()), "checks": checks}


class ChangeFixture(FixtureServer):
    def __init__(self, *, seed: int, port: int) -> None:
        super().__init__(seed=seed, port=port)
        self.stream = SeqStream(
            seed=seed,
            name="orders",
            generate=order_for_seq,
            page_limit=PAGE_LIMIT,
        )
        self.owner = install_owner_channel(self)
        self.route("GET", "/orders", self._orders)
        self.route("GET", "/refunds", self._refunds)
        self.route(
            "GET",
            "/batches/last",
            lambda _r: (200, {"last_seq": self.last_seq()}),
        )
        self.route("GET", "/batches", lambda _r: (200, self.batches()))
        self.route("POST", "/batches", self._post_batch)

    def _orders(self, r: Request) -> tuple[int, Any]:
        try:
            after = int(r.q("after") or "0")
        except ValueError:
            return 400, {"error": "after must be an integer"}
        r.server.waypoints.reach("read_orders", after=after)
        return 200, self.stream.rows_after(after)

    def _refunds(self, r: Request) -> tuple[int, Any]:
        try:
            start = int(r.q("start_seq") or "")
            end = int(r.q("end_seq") or "")
        except ValueError:
            return 400, {"error": "start_seq and end_seq must be integers"}
        r.server.waypoints.reach("read_refunds", start_seq=start, end_seq=end)
        return 200, refunds_in_range(self.seed, start, end)

    def _post_batch(self, r: Request) -> tuple[int, Any]:
        r.server.recorder.record("batch", r.body)
        return 200, {"status": "received"}

    def batches(self) -> list[Any]:
        return [e["payload"] for e in self.recorder.all("batch")]

    def last_seq(self) -> int:
        last = 0
        for body in self.batches():
            if isinstance(body, dict):
                try:
                    last = max(last, int(body.get("batch_end_seq") or 0))
                except (TypeError, ValueError):
                    continue
        return last


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT):
    return ChangeFixture(seed=seed, port=port)
