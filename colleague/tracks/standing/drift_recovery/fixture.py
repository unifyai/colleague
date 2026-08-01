"""Order-stream fixture for the drift-recovery benchmark.

A deterministic, seeded stream of orders keyed by an integer ``seq``. The
harness "releases" new orders before each fire, the system under test
processes the next unprocessed range and POSTs a batch summary, and the sink
itself is the cursor (``/batches/last``) — so the workflow is stateless and
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
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

REGIONS = ("north", "south", "east", "west")
BASE_PRICE_CENTS = {"north": 1999, "south": 1499, "east": 2499, "west": 999}
STREAM_START_DATE = date(2026, 7, 1)
ORDERS_PER_DAY = 12
PAGE_LIMIT = 200

DEFAULT_SEED = 20260731
DEFAULT_PORT = 8125


def order_for_seq(seed: int, seq: int) -> dict[str, Any]:
    """The unique order at position ``seq`` (1-based), deterministic in (seed, seq)."""
    payload = f"{seed}:order:{seq}".encode()
    h = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
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


@dataclass
class OrderStream:
    """Mutable fixture state shared between the HTTP handler and the harness."""

    seed: int = DEFAULT_SEED
    released_seq: int = 0
    drifted: bool = False
    batches: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def release(self, count: int) -> int:
        with self._lock:
            self.released_seq += count
            return self.released_seq

    def set_drift(self, drifted: bool) -> None:
        with self._lock:
            self.drifted = drifted

    def orders_after(self, after: int) -> list[dict[str, Any]]:
        with self._lock:
            released = self.released_seq
            drifted = self.drifted
        start = max(after, 0) + 1
        end = min(released, start + PAGE_LIMIT - 1)
        rows = [order_for_seq(self.seed, seq) for seq in range(start, end + 1)]
        if drifted:
            rows = [
                {
                    ("unit_price_minor" if k == "unit_price_cents" else k): v
                    for k, v in row.items()
                }
                for row in rows
            ]
        return rows

    def add_batch(self, body: Any) -> None:
        with self._lock:
            self.batches.append(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                },
            )

    def last_processed_seq(self) -> int:
        with self._lock:
            last = 0
            for entry in self.batches:
                body = entry.get("body")
                if isinstance(body, dict):
                    try:
                        last = max(last, int(body.get("batch_end_seq") or 0))
                    except (TypeError, ValueError):
                        continue
            return last

    def snapshot_batches(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.batches)


class _Handler(BaseHTTPRequestHandler):
    stream: OrderStream

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
                after = int(params.get("after", ["0"])[0])
            except ValueError:
                self._send_json(400, {"error": "after must be an integer"})
                return
            self._send_json(200, self.stream.orders_after(after))
            return
        if parsed.path == "/batches/last":
            self._send_json(200, {"last_seq": self.stream.last_processed_seq()})
            return
        if parsed.path == "/batches":
            self._send_json(200, self.stream.snapshot_batches())
            return
        self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/batches":
            self._send_json(404, {"error": f"unknown path {parsed.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "body must be valid JSON"})
            return
        self.stream.add_batch(body)
        self._send_json(200, {"status": "received"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class DriftFixtureServer:
    """In-process fixture server bound to 127.0.0.1."""

    def __init__(self, *, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> None:
        self.stream = OrderStream(seed=seed)
        handler = type("BoundHandler", (_Handler,), {"stream": self.stream})
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="drift-fixture-server",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "DriftFixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
