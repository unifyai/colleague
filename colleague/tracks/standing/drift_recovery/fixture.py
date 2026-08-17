"""Order-stream fixture for the drift-recovery benchmark.

A deterministic, seeded stream of orders keyed by an integer ``seq``. The
harness "releases" new orders before each fire, the system under test
processes the next unprocessed range and POSTs a batch summary, and the sink
itself is the cursor (``/batches/last``) — so the automation is stateless and
fire-timing-independent by construction.

Mid-series the harness flips ``drifted``: ``/orders`` renames
``unit_price_cents`` to ``unit_price_minor`` (values identical) — the
smallest realistic API drift. Ground truth is computed from the generator
and is unaffected by the rename; the batch contract POSTed to ``/batches``
never changes.

Endpoints:
    GET  /health                      -> {"status": "ok"}
    GET  /orders?after=N              -> up to 200 orders with seq > N, ascending
    GET  /batches/last                -> {"last_seq": highest processed seq (0 if none)}
    POST /batches                     -> stores the JSON body
    GET  /batches                     -> all stored batches (with receipt metadata)
    POST /owner/notify                -> {"message": ...} (not advertised in this
                                         experiment's utterance; see protocol.py)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from colleague.harness.fixture_server import FixtureServer, Request, utcnow
from colleague.tracks.standing.series.spec import install_owner_channel
from colleague.tracks.standing.series.streams import SeqStream, hash_for

REGIONS = ("north", "south", "east", "west")
BASE_PRICE_CENTS = {"north": 1999, "south": 1499, "east": 2499, "west": 999}
STREAM_START_DATE = date(2026, 7, 1)
ORDERS_PER_DAY = 12
PAGE_LIMIT = 200

DEFAULT_SEED = 20260731
DEFAULT_PORT = 8125


def order_for_seq(seed: int, seq: int) -> dict[str, Any]:
    """The unique order at position ``seq`` (1-based), deterministic in (seed, seq)."""
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


def expected_batch(seed: int, start_seq: int, end_seq: int) -> dict[str, Any]:
    """The exact batch summary a correct implementation must POST for a range."""
    total_units = 0
    total_revenue = 0
    by_region: dict[str, int] = {}
    for seq in range(start_seq, end_seq + 1):
        row = order_for_seq(seed, seq)
        revenue = row["units"] * row["unit_price_cents"]
        total_units += row["units"]
        total_revenue += revenue
        by_region[row["region"]] = by_region.get(row["region"], 0) + revenue
    return {
        "batch_start_seq": start_seq,
        "batch_end_seq": end_seq,
        "order_count": end_seq - start_seq + 1,
        "total_units": total_units,
        "total_revenue_cents": total_revenue,
        "revenue_by_region_cents": by_region,
    }


def score_batch(actual: Any, expected: dict[str, Any]) -> dict[str, Any]:
    """Field-by-field exact comparison of a posted batch against ground truth."""
    if not isinstance(actual, dict):
        return {"correct": False, "checks": {"is_json_object": False}}
    checks: dict[str, bool] = {"is_json_object": True}
    for key in (
        "batch_start_seq",
        "batch_end_seq",
        "order_count",
        "total_units",
        "total_revenue_cents",
        "revenue_by_region_cents",
    ):
        checks[key] = actual.get(key) == expected[key]
    extra_keys = sorted(set(actual) - set(expected))
    checks["no_extra_keys"] = not extra_keys
    return {"correct": all(checks.values()), "checks": checks, "extra_keys": extra_keys}


def _rename_unit_price(row: dict[str, Any]) -> dict[str, Any]:
    return {
        ("unit_price_minor" if k == "unit_price_cents" else k): v
        for k, v in row.items()
    }


class DriftFixtureServer(FixtureServer):
    """In-process fixture server bound to 127.0.0.1."""

    def __init__(self, *, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> None:
        super().__init__(seed=seed, port=port)
        self.stream = SeqStream(
            seed=seed,
            name="orders",
            generate=order_for_seq,
            page_limit=PAGE_LIMIT,
        )
        self.owner = install_owner_channel(self)
        self.route("GET", "/orders", self._orders)
        self.route(
            "GET",
            "/batches/last",
            lambda _r: (200, {"last_seq": self.last_seq()}),
        )
        self.route("GET", "/batches", lambda _r: (200, self.batches_with_receipts()))
        self.route("POST", "/batches", self._post_batch)

    def set_drift(self, drifted: bool) -> None:
        self.stream.set_transform(_rename_unit_price if drifted else None)

    def _orders(self, r: Request) -> tuple[int, Any]:
        try:
            after = int(r.q("after") or "0")
        except ValueError:
            return 400, {"error": "after must be an integer"}
        r.server.waypoints.reach("read_orders", after=after)
        return 200, self.stream.rows_after(after)

    def _post_batch(self, r: Request) -> tuple[int, Any]:
        r.server.recorder.record("batch", r.body, received_at=utcnow())
        return 200, {"status": "received"}

    def batches(self) -> list[Any]:
        return [e["payload"] for e in self.recorder.all("batch")]

    def batches_with_receipts(self) -> list[dict[str, Any]]:
        return [
            {"received_at": e.get("received_at"), "body": e["payload"]}
            for e in self.recorder.all("batch")
        ]

    def last_seq(self) -> int:
        last = 0
        for body in self.batches():
            if isinstance(body, dict):
                try:
                    last = max(last, int(body.get("batch_end_seq") or 0))
                except (TypeError, ValueError):
                    continue
        return last
