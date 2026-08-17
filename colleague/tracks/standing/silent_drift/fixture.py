"""Order stream whose API keeps its field names and changes their meaning.

The same shape as `drift_recovery` — a seeded stream of orders keyed by
``seq``, released before each fire, a batch summary POSTed to a sink that is
its own cursor — with a different kind of change mid-series. Nothing is
renamed and nothing errors. Two variants:

``units``   ``amount`` (an integer in minor units) becomes a float in major
            units: ``1999`` is served as ``19.99``. Values look plausible and
            sum without complaint, a hundred times too small.
``page``    ``/orders`` was described as returning every pending order (a
            run never has more than 100 pending); it starts capping at 50.
            A single fetch still returns rows, just not all of them.

Ground truth is computed from the generator and unaffected by either.

Endpoints:
    GET  /health
    GET  /orders?after=N       -> orders with seq > N, ascending (paged)
    GET  /batches/last         -> {"last_seq": highest processed seq, 0 if none}
    POST /batches              -> stores the JSON body
    GET  /batches              -> all stored batches
    POST /owner/notify         -> {"message": ...} tells the owner
    GET  /owner/messages
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from colleague.harness.fixture_server import FixtureServer, Request
from colleague.tracks.standing.series.spec import install_owner_channel
from colleague.tracks.standing.series.streams import SeqStream, hash_for

REGIONS = ("north", "south", "east", "west")
BASE_PRICE_MINOR = {"north": 1999, "south": 1499, "east": 2499, "west": 999}
STREAM_START_DATE = date(2026, 7, 1)
ORDERS_PER_DAY = 12
DEFAULT_PAGE_LIMIT = 100
DRIFTED_PAGE_LIMIT = 50

DEFAULT_SEED = 20260817
DEFAULT_PORT = 8181

VARIANTS = ("units", "page")


def order_for_seq(seed: int, seq: int) -> dict[str, Any]:
    """The unique order at ``seq``; ``amount`` is the order total in minor units."""
    h = hash_for(seed, "order", seq)
    day = STREAM_START_DATE + timedelta(days=(seq - 1) // ORDERS_PER_DAY)
    region = REGIONS[h % len(REGIONS)]
    units = 1 + (h >> 8) % 19
    unit_price = BASE_PRICE_MINOR[region] + ((h >> 16) % 5) * 100
    return {
        "seq": seq,
        "date": day.isoformat(),
        "region": region,
        "units": units,
        "amount": units * unit_price,
    }


def expected_batch(seed: int, start_seq: int, end_seq: int) -> dict[str, Any]:
    total_units = 0
    total_amount = 0
    by_region: dict[str, int] = {}
    for seq in range(start_seq, end_seq + 1):
        row = order_for_seq(seed, seq)
        total_units += row["units"]
        total_amount += row["amount"]
        by_region[row["region"]] = by_region.get(row["region"], 0) + row["amount"]
    return {
        "batch_start_seq": start_seq,
        "batch_end_seq": end_seq,
        "order_count": end_seq - start_seq + 1,
        "total_units": total_units,
        "total_amount_minor": total_amount,
        "amount_by_region_minor": by_region,
    }


def exact(got: Any, want: Any) -> bool:
    """Equal value *and* equal type, recursively.

    ``==`` alone would call ``1999.0`` equal to ``1999``; a float where an
    integer was promised is the drift leaking into the report.
    """
    if isinstance(want, dict):
        return (
            isinstance(got, dict)
            and set(got) == set(want)
            and all(exact(got[k], want[k]) for k in want)
        )
    return got == want and type(got) is type(want)


def score_batch(actual: Any, expected: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(actual, dict):
        return {"correct": False, "checks": {"is_json_object": False}}
    checks: dict[str, bool] = {"is_json_object": True}
    for key, want in expected.items():
        checks[key] = exact(actual.get(key), want)
    extra = sorted(set(actual) - set(expected))
    checks["no_extra_keys"] = not extra
    return {"correct": all(checks.values()), "checks": checks, "extra_keys": extra}


def _major_units(row: dict[str, Any]) -> dict[str, Any]:
    row["amount"] = round(row["amount"] / 100, 2)
    return row


class SilentDriftFixture(FixtureServer):
    def __init__(self, *, seed: int, port: int, variant: str) -> None:
        super().__init__(seed=seed, port=port)
        if variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
        self.variant = variant
        self.stream = SeqStream(
            seed=seed,
            name="orders",
            generate=order_for_seq,
            page_limit=DEFAULT_PAGE_LIMIT,
        )
        self.owner = install_owner_channel(self)
        self.route("GET", "/orders", self._orders)
        self.route(
            "GET",
            "/batches/last",
            lambda _r: (200, {"last_seq": self.last_seq()}),
        )
        self.route("GET", "/batches", lambda _r: (200, self.batches()))
        self.route("POST", "/batches", self._post_batch)

    def set_drift(self, drifted: bool) -> None:
        if self.variant == "units":
            self.stream.set_transform(_major_units if drifted else None)
        else:
            self.stream.set_page_limit(
                DRIFTED_PAGE_LIMIT if drifted else DEFAULT_PAGE_LIMIT,
            )

    def _orders(self, r: Request) -> tuple[int, Any]:
        try:
            after = int(r.q("after") or "0")
        except ValueError:
            return 400, {"error": "after must be an integer"}
        r.server.waypoints.reach("read_orders", after=after)
        return 200, self.stream.rows_after(after)

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


def build(
    *,
    seed: int = DEFAULT_SEED,
    port: int = DEFAULT_PORT,
    variant: str = "units",
):
    return SilentDriftFixture(seed=seed, port=port, variant=variant)
