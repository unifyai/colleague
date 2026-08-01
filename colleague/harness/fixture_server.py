"""A routed, seeded fixture server with observable waypoints.

The `standing` experiments each grew their own `ThreadingHTTPServer` with a
hand-rolled `do_GET`/`do_POST`. That was fine for four experiments that only
needed to serve data and collect a POST. The multi-party tracks need two
things those fixtures never did:

**Waypoints.** The harness has to know when the agent under test has reached
a particular point in its own work — read the recipient list, authenticated,
fetched the ledger — so a scripted message can be injected *there* rather
than after an arbitrary sleep. Sleeps make cached and live runs order
differently, which is exactly the failure mode the trigger helpers in unify's
test suite exist to prevent.

**Side-effect recording.** Every track here is scored on what the agent
*did* — which address received mail, which row was written, whether anything
was sent at all. The fixture is the only honest witness to that, so it
records every mutating call with a sequence number and a timestamp.

A route handler takes a `Request` and returns `(status, payload)`. Anything
it wants remembered it records; anything it wants the harness to be able to
wait for it marks as a waypoint.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


def stable_hash(seed: int, *parts: Any) -> int:
    """Deterministic 64-bit hash, so fixtures are reproducible across runs."""
    payload = ":".join([str(seed), *map(str, parts)]).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Waypoints:
    """Named points in the agent's progress that the harness can wait on.

    A waypoint is reached by the fixture when it observes the agent doing
    something specific. `wait_for` blocks until that happens, which is what
    lets the interlocutor inject a message at a repeatable moment instead of
    guessing with a sleep.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._events: dict[str, threading.Event] = {}
        self._log: list[dict[str, Any]] = []

    def _event(self, name: str) -> threading.Event:
        if name not in self._events:
            self._events[name] = threading.Event()
        return self._events[name]

    def reach(self, name: str, **detail: Any) -> int:
        """Signal that the agent has reached ``name``. Returns the hit count."""
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + 1
            count = self._counts[name]
            self._log.append(
                {"waypoint": name, "n": count, "at": utcnow(), **detail},
            )
            self._event(name).set()
        return count

    def wait_for(self, name: str, timeout: float = 120.0, *, nth: int = 1) -> bool:
        """Block until ``name`` has been reached ``nth`` times, or timeout."""
        deadline = threading.Event()
        del deadline
        import time

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if self._counts.get(name, 0) >= nth:
                    return True
                event = self._event(name)
                event.clear()
            event.wait(timeout=min(0.25, max(0.0, end - time.monotonic())))
        with self._lock:
            return self._counts.get(name, 0) >= nth

    def count(self, name: str) -> int:
        with self._lock:
            return self._counts.get(name, 0)

    def log(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._log)


class Recorder:
    """Every mutating call the fixture saw, in order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []

    def record(self, kind: str, payload: Any, **meta: Any) -> int:
        with self._lock:
            seq = len(self._entries) + 1
            self._entries.append(
                {
                    "seq": seq,
                    "kind": kind,
                    "at": utcnow(),
                    "payload": payload,
                    **meta,
                },
            )
            return seq

    def all(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            entries = list(self._entries)
        return [e for e in entries if kind is None or e["kind"] == kind]

    def count(self, kind: str | None = None) -> int:
        return len(self.all(kind))


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    body: Any
    server: "FixtureServer"

    def q(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name)
        return values[0] if values else default


Handler = Callable[[Request], "tuple[int, Any]"]


@dataclass
class Route:
    method: str
    path: str
    handler: Handler
    hold_ms: int = 0
    """Delay applied before responding.

    Used only to guarantee an injection window exists at a known point. The
    injection itself is keyed to a waypoint, never to this delay, so the
    ordering stays deterministic if the delay is tuned.
    """


class _Handler(BaseHTTPRequestHandler):
    fixture: "FixtureServer"

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        body: Any = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode() or "null")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "body must be valid JSON"})
                return

        route = self.fixture.match(method, parsed.path)
        if route is None:
            self._send_json(404, {"error": f"unknown path {method} {parsed.path}"})
            return

        request = Request(
            method=method,
            path=parsed.path,
            query=parse_qs(parsed.query),
            body=body,
            server=self.fixture,
        )
        status, payload = route.handler(request)
        if route.hold_ms:
            import time

            time.sleep(route.hold_ms / 1000.0)
        self._send_json(status, payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("DELETE")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class FixtureServer:
    """In-process fixture bound to 127.0.0.1, with waypoints and a recorder."""

    def __init__(self, *, seed: int, port: int = 0) -> None:
        self.seed = seed
        self.waypoints = Waypoints()
        self.recorder = Recorder()
        self.state: dict[str, Any] = {}
        self._routes: list[Route] = []
        self._lock = threading.Lock()

        self.route("GET", "/health", lambda _r: (200, {"status": "ok"}))

        handler = type("BoundHandler", (_Handler,), {"fixture": self})
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"fixture-{seed}",
            daemon=True,
        )

    def route(
        self,
        method: str,
        path: str,
        handler: Handler,
        *,
        hold_ms: int = 0,
    ) -> None:
        self._routes.append(Route(method, path, handler, hold_ms=hold_ms))

    def match(self, method: str, path: str) -> Route | None:
        for route in self._routes:
            if route.method == method and route.path == path:
                return route
        return None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "FixtureServer":
        self._thread.start()
        self._started = True
        return self

    def stop(self) -> None:
        # shutdown() blocks until serve_forever's loop acknowledges it, which
        # never happens if the server was built but never started. Guarding
        # here rather than at call sites: a fixture that is constructed and
        # discarded is an ordinary thing to do, and it should not hang.
        if getattr(self, "_started", False):
            self._server.shutdown()
        self._server.server_close()
        self._started = False

    def __enter__(self) -> "FixtureServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def evidence(self) -> dict[str, Any]:
        """Everything the fixture witnessed, for the run record."""
        return {
            "waypoints": self.waypoints.log(),
            "recorded": self.recorder.all(),
        }
