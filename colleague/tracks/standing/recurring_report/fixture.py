"""Deterministic orders API + report sink for the recurring weekly report benchmark.

Everything is seeded and stdlib-only so any third party can reproduce the
exact same data and ground truth. The server is the benchmark's "external
world": the system under test fetches orders from it and delivers reports to
it, and the harness independently recomputes what a correct report must
contain.

Endpoints:
    GET  /health                              -> {"status": "ok"}
    GET  /orders?start=YYYY-MM-DD&end=YYYY-MM-DD
        -> JSON list of orders in [start, end] inclusive, each:
           {order_id, date, region, units, unit_price_cents}
    POST /report                              -> stores the JSON body
    GET  /reports                             -> all stored reports (with receipt metadata)

Run standalone for manual poking:
    python colleague/tracks/standing/recurring_report/fixture.py --port 8123 --seed 20260731
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse, parse_qs

REGIONS = ("north", "south", "east", "west")
BASE_PRICE_CENTS = {"north": 1999, "south": 1499, "east": 2499, "west": 999}

DEFAULT_SEED = 20260731
DEFAULT_PORT = 8123


# --------------------------------------------------------------------------- #
# Deterministic data generation                                               #
# --------------------------------------------------------------------------- #


def _h(seed: int, *parts: Any) -> int:
    """Stable 64-bit hash of the seed plus any parts."""
    payload = ":".join([str(seed), *map(str, parts)]).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def orders_for_date(seed: int, day: date) -> list[dict[str, Any]]:
    """All orders for one calendar day, deterministic in (seed, day)."""
    rows: list[dict[str, Any]] = []
    for region in REGIONS:
        n_orders = 1 + _h(seed, day.isoformat(), region) % 3
        for i in range(n_orders):
            oh = _h(seed, day.isoformat(), region, i)
            rows.append(
                {
                    "order_id": f"{day.isoformat()}-{region}-{i}",
                    "date": day.isoformat(),
                    "region": region,
                    "units": 1 + oh % 19,
                    "unit_price_cents": BASE_PRICE_CENTS[region]
                    + ((oh >> 8) % 5) * 100,
                },
            )
    return rows


def orders_in_range(seed: int, start: date, end: date) -> list[dict[str, Any]]:
    """All orders with start <= date <= end."""
    rows: list[dict[str, Any]] = []
    day = start
    while day <= end:
        rows.extend(orders_for_date(seed, day))
        day += timedelta(days=1)
    return rows


# --------------------------------------------------------------------------- #
# Ground truth                                                                #
# --------------------------------------------------------------------------- #


def report_week_bounds(run_date: date) -> tuple[date, date]:
    """The report week for a run: the last full Monday-Sunday before run_date."""
    week_start = run_date - timedelta(days=run_date.weekday() + 7)
    return week_start, week_start + timedelta(days=6)


def _aggregate(seed: int, start: date, end: date) -> tuple[int, int, dict[str, int]]:
    total_units = 0
    total_revenue = 0
    by_region = {region: 0 for region in REGIONS}
    for row in orders_in_range(seed, start, end):
        revenue = row["units"] * row["unit_price_cents"]
        total_units += row["units"]
        total_revenue += revenue
        by_region[row["region"]] += revenue
    return total_units, total_revenue, by_region


def expected_report(seed: int, run_date: date) -> dict[str, Any]:
    """The exact report a correct implementation must deliver for run_date."""
    week_start, week_end = report_week_bounds(run_date)
    units, revenue, by_region = _aggregate(seed, week_start, week_end)
    _, prev_revenue, _ = _aggregate(
        seed,
        week_start - timedelta(days=7),
        week_start - timedelta(days=1),
    )
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_units": units,
        "total_revenue_cents": revenue,
        "revenue_by_region_cents": by_region,
        "wow_revenue_change_pct": round(
            (revenue - prev_revenue) / prev_revenue * 100,
            2,
        ),
    }


def score_report(actual: Any, expected: dict[str, Any]) -> dict[str, Any]:
    """Field-by-field exact comparison of a delivered report against ground truth."""
    checks: dict[str, bool] = {}
    if not isinstance(actual, dict):
        return {"correct": False, "checks": {"is_json_object": False}}
    checks["is_json_object"] = True
    for key in ("week_start", "week_end"):
        checks[key] = actual.get(key) == expected[key]
    for key in ("total_units", "total_revenue_cents"):
        checks[key] = actual.get(key) == expected[key]
    checks["revenue_by_region_cents"] = (
        actual.get("revenue_by_region_cents") == expected["revenue_by_region_cents"]
    )
    wow = actual.get("wow_revenue_change_pct")
    checks["wow_revenue_change_pct"] = (
        isinstance(wow, (int, float))
        and abs(float(wow) - expected["wow_revenue_change_pct"]) <= 0.005
    )
    extra_keys = sorted(set(actual) - set(expected))
    checks["no_extra_keys"] = not extra_keys
    return {
        "correct": all(checks.values()),
        "checks": checks,
        "extra_keys": extra_keys,
    }


# --------------------------------------------------------------------------- #
# HTTP server                                                                 #
# --------------------------------------------------------------------------- #


@dataclass
class ReportSink:
    """Thread-safe store of delivered reports."""

    reports: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, body: Any) -> None:
        with self._lock:
            self.reports.append(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                },
            )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.reports)


class _Handler(BaseHTTPRequestHandler):
    seed: int = DEFAULT_SEED
    sink: ReportSink

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/orders":
            params = parse_qs(parsed.query)
            try:
                start = date.fromisoformat(params["start"][0])
                end = date.fromisoformat(params["end"][0])
            except (KeyError, ValueError):
                self._send_json(
                    400,
                    {"error": "start and end query params required, YYYY-MM-DD"},
                )
                return
            if end < start:
                self._send_json(400, {"error": "end must be >= start"})
                return
            self._send_json(200, orders_in_range(self.seed, start, end))
            return
        if parsed.path == "/reports":
            self._send_json(200, self.sink.snapshot())
            return
        self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/report":
            self._send_json(404, {"error": f"unknown path {parsed.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "body must be valid JSON"})
            return
        self.sink.add(body)
        self._send_json(200, {"status": "received"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # keep benchmark output clean; requests are visible via the sink


class FixtureServer:
    """In-process fixture server bound to 127.0.0.1."""

    def __init__(self, *, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> None:
        self.seed = seed
        self.sink = ReportSink()
        handler = type(
            "BoundHandler",
            (_Handler,),
            {"seed": seed, "sink": self.sink},
        )
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rwr-fixture-server",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "FixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    server = FixtureServer(seed=args.seed, port=args.port).start()
    print(f"Fixture server on {server.base_url} (seed={args.seed}). Ctrl-C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
