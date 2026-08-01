"""Three digests being set up at once, and corrections about specific ones.

Each digest is created through the same endpoint, so the fixture reaches a
waypoint per creation. Corrections are injected after the first and second
creations — while the third is still being written — which is what makes the
routing question real: at the moment the correction arrives, the agent is
mid-way through a batch and has to work out which member it concerns.

Final state is the score. A correction that lands on the wrong digest is
visible as the wrong digest having changed.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.fixture_server import FixtureServer, Request

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8145

EXPECTED_NAMES = ("sales", "support", "finance")


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["digests"] = {}

    def create(r: Request) -> tuple[int, Any]:
        body = r.body or {}
        name = str(body.get("name", "")).strip().lower()
        if not name:
            return 400, {"error": "name is required"}
        fx.state["digests"][name] = {
            "name": name,
            "frequency": str(body.get("frequency", "")).strip().lower(),
            "recipient": str(body.get("recipient", "")).strip().lower(),
        }
        n = r.server.waypoints.reach("digest_created", digest=name)
        r.server.recorder.record("create", fx.state["digests"][name], n=n)
        return 200, {"status": "created", "digest": fx.state["digests"][name]}

    def update(r: Request) -> tuple[int, Any]:
        body = r.body or {}
        name = str(body.get("name", "")).strip().lower()
        if name not in fx.state["digests"]:
            return 404, {"error": f"no digest named {name!r}"}
        for field in ("frequency", "recipient"):
            if body.get(field):
                fx.state["digests"][name][field] = str(body[field]).strip().lower()
        r.server.waypoints.reach("digest_updated", digest=name)
        r.server.recorder.record("update", {"name": name, **body})
        return 200, {"status": "updated", "digest": fx.state["digests"][name]}

    def listing(r: Request) -> tuple[int, Any]:
        return 200, list(fx.state["digests"].values())

    fx.route("POST", "/digests", create, hold_ms=400)
    fx.route("POST", "/digests/update", update)
    fx.route("GET", "/digests", listing)
    return fx


API_DOC = """\
Digest API at {base_url}:
  POST {base_url}/digests        -> body {{"name": "<str>", "frequency": "<str>", "recipient": "<str>"}}
  POST {base_url}/digests/update -> body {{"name": "<str>", "frequency": "<str>?", "recipient": "<str>?"}}
  GET  {base_url}/digests        -> current state of all digests\
"""
