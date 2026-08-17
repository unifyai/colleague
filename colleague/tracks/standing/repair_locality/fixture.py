"""Three independent streams feeding one report; only one of them drifts.

Orders, refunds and tickets are separate seeded streams, each keyed by its
own ``seq`` and each with its own cursor in the last report. The automation
reads all three, computes a section per stream, and POSTs one report. Before
fire 5 the refunds API renames ``amount_cents`` to ``amount_minor``; orders
and tickets never change.

Ground truth is per section, so the scorer can say which section broke and
which stayed right — and can compare the *shape* of the untouched sections
before and after whatever repair the arm makes.

Endpoints:
    GET  /health
    GET  /reports/last     -> {"orders_last_seq", "refunds_last_seq", "tickets_last_seq"}
    GET  /orders?after=N   -> orders with seq > N (up to 200)
    GET  /refunds?after=N  -> refunds with seq > N (up to 200)
    GET  /tickets?after=N  -> tickets with seq > N (up to 200)
    POST /report           -> {"orders": {...}, "refunds": {...}, "tickets": {...}}
    GET  /reports
    POST /owner/notify     -> {"message": ...}
    GET  /owner/messages
"""

from __future__ import annotations

from typing import Any

from colleague.harness.fixture_server import FixtureServer, Request
from colleague.tracks.standing.series.spec import install_owner_channel, json_shape
from colleague.tracks.standing.series.streams import SeqStream, hash_for

DEFAULT_SEED = 20260817
DEFAULT_PORT = 8183
PAGE_LIMIT = 200

REGIONS = ("north", "south", "east", "west")
BASE_PRICE_CENTS = {"north": 1999, "south": 1499, "east": 2499, "west": 999}
PRIORITIES = ("low", "normal", "high")
STREAMS = ("orders", "refunds", "tickets")


def order_for_seq(seed: int, seq: int) -> dict[str, Any]:
    h = hash_for(seed, "order", seq)
    region = REGIONS[h % len(REGIONS)]
    return {
        "seq": seq,
        "region": region,
        "units": 1 + (h >> 8) % 19,
        "unit_price_cents": BASE_PRICE_CENTS[region] + ((h >> 16) % 5) * 100,
    }


def refund_for_seq(seed: int, seq: int) -> dict[str, Any]:
    h = hash_for(seed, "refund", seq)
    return {
        "seq": seq,
        "order_seq": 1 + (h % 400),
        "amount_cents": 500 + (h >> 8) % 9000,
        "reason": ("damaged", "late", "wrong_item")[(h >> 24) % 3],
    }


def ticket_for_seq(seed: int, seq: int) -> dict[str, Any]:
    h = hash_for(seed, "ticket", seq)
    return {
        "seq": seq,
        "priority": PRIORITIES[h % len(PRIORITIES)],
        "channel": ("email", "chat", "phone")[(h >> 8) % 3],
    }


GENERATORS = {
    "orders": order_for_seq,
    "refunds": refund_for_seq,
    "tickets": ticket_for_seq,
}


def expected_sections(
    seed: int,
    ranges: dict[str, tuple[int, int]],
) -> dict[str, dict[str, Any]]:
    """The three sections a correct report carries for the given seq ranges."""
    o_start, o_end = ranges["orders"]
    orders = [order_for_seq(seed, s) for s in range(o_start, o_end + 1)]
    r_start, r_end = ranges["refunds"]
    refunds = [refund_for_seq(seed, s) for s in range(r_start, r_end + 1)]
    t_start, t_end = ranges["tickets"]
    tickets = [ticket_for_seq(seed, s) for s in range(t_start, t_end + 1)]
    by_priority = {p: 0 for p in PRIORITIES}
    for t in tickets:
        by_priority[t["priority"]] += 1
    return {
        "orders": {
            "start_seq": o_start,
            "end_seq": o_end,
            "count": len(orders),
            "total_units": sum(o["units"] for o in orders),
            "total_revenue_cents": sum(
                o["units"] * o["unit_price_cents"] for o in orders
            ),
        },
        "refunds": {
            "start_seq": r_start,
            "end_seq": r_end,
            "count": len(refunds),
            "total_refunded_cents": sum(r["amount_cents"] for r in refunds),
        },
        "tickets": {
            "start_seq": t_start,
            "end_seq": t_end,
            "count": len(tickets),
            "by_priority": by_priority,
        },
    }


def score_report(actual: Any, expected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(actual, dict):
        return {
            "exact": False,
            "sections_correct": {s: False for s in STREAMS},
            "shapes": {},
        }
    sections_correct = {}
    shapes = {}
    for name in STREAMS:
        got = actual.get(name)
        sections_correct[name] = got == expected[name] and not (
            isinstance(got, dict) and set(got) - set(expected[name])
        )
        shapes[name] = json_shape(got)
    extra = sorted(set(actual) - set(STREAMS))
    return {
        "exact": all(sections_correct.values()) and not extra,
        "sections_correct": sections_correct,
        "shapes": shapes,
        "extra_keys": extra,
    }


def _rename_amount(row: dict[str, Any]) -> dict[str, Any]:
    return {("amount_minor" if k == "amount_cents" else k): v for k, v in row.items()}


class RepairLocalityFixture(FixtureServer):
    def __init__(self, *, seed: int, port: int) -> None:
        super().__init__(seed=seed, port=port)
        self.streams = {
            name: SeqStream(seed=seed, name=name, generate=gen, page_limit=PAGE_LIMIT)
            for name, gen in GENERATORS.items()
        }
        self.owner = install_owner_channel(self)
        for name in STREAMS:
            self.route("GET", f"/{name}", self._reader(name))
        self.route("GET", "/reports/last", lambda _r: (200, self.cursors()))
        self.route("GET", "/reports", lambda _r: (200, self.reports()))
        self.route("POST", "/report", self._post_report)

    def set_drift(self, drifted: bool) -> None:
        self.streams["refunds"].set_transform(_rename_amount if drifted else None)

    def _reader(self, name: str):
        def read(r: Request) -> tuple[int, Any]:
            try:
                after = int(r.q("after") or "0")
            except ValueError:
                return 400, {"error": "after must be an integer"}
            r.server.waypoints.reach(f"read_{name}", after=after)
            return 200, self.streams[name].rows_after(after)

        return read

    def _post_report(self, r: Request) -> tuple[int, Any]:
        r.server.recorder.record("report", r.body)
        return 200, {"status": "received"}

    def reports(self) -> list[Any]:
        return [e["payload"] for e in self.recorder.all("report")]

    def cursors(self) -> dict[str, int]:
        last = {name: 0 for name in STREAMS}
        for body in self.reports():
            if not isinstance(body, dict):
                continue
            for name in STREAMS:
                section = body.get(name)
                if isinstance(section, dict):
                    try:
                        last[name] = max(last[name], int(section.get("end_seq") or 0))
                    except (TypeError, ValueError):
                        continue
        return {f"{name}_last_seq": last[name] for name in STREAMS}


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT):
    return RepairLocalityFixture(seed=seed, port=port)
