"""Replay a stored entrypoint against the fixture, for free.

A committed run carries the function the system distilled from it, so its
detection behaviour can be re-checked without paying for inference: serve the
fixture, exec the stored implementation with the narrative LLM call stubbed,
and score what it posts. Every part of the function that decides *what to
flag* is ordinary Python and runs for real; only the prose is faked.

Use this whenever the fixture changes, before spending on a live run. It is
how the eleven-plant fixture was verified: the entrypoint from the
2026-08-04T17-36-52Z run flags 11/11 against it, 13 drafted and only the
expired-connection client blocked.

    python -m colleague.tracks.usecases.agency_client_reporting.replay_entrypoint

Binds the fixture to the port baked into the stored function's own URLs, so it
cannot run while a live measurement is in flight.

**Reproducing a defect in a stored function** needs a source edit, not a
monkeypatch. These functions define their helpers *nested inside* themselves,
so rebinding a name in the function's globals is silently ignored — patch a
copy of `entrypoint_function.implementation` and exec that instead.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
from pathlib import Path
from typing import Any

from colleague.tracks.usecases.agency_client_reporting.fixture import (
    DEFAULT_PORT,
    DEFAULT_SEED,
    FixtureServer,
    default_anchor,
)
from colleague.tracks.usecases.agency_client_reporting.fixture import (
    selftest as fixture_selftest,
)
from colleague.tracks.usecases.agency_client_reporting.protocol import score_run

EXPERIMENT_DIR = Path(__file__).resolve().parent

# Distilled functions each invent their own narrative contract — one run asked
# for `changes`, another for `what_wed_change` — and they validate it strictly,
# so a fixed stub blocks every report and looks like a detection failure. The
# stub reads the field names out of the prompt instead, since the prompt states
# them, and falls back to the union of the shapes seen so far.
STUB_FIELDS_FALLBACK = (
    "what_happened",
    "why",
    "changes",
    "what_wed_change",
    "summary",
)

_FIELDS_RE = re.compile(
    r"fields?:?\s+((?:[a-z_]+(?:\s*,\s*|\s+and\s+))+[a-z_]+)",
    re.IGNORECASE,
)


def stub_narrative(prompt: str) -> dict[str, str]:
    """A narrative payload satisfying whatever fields the prompt demands."""
    fields = set(STUB_FIELDS_FALLBACK)
    match = _FIELDS_RE.search(prompt)
    if match:
        named = re.split(r"\s*,\s*|\s+and\s+", match.group(1))
        fields |= {f.strip() for f in named if f.strip()}
    return {f: "stubbed narrative" for f in fields}


def latest_results(results_dir: Path | None = None) -> Path:
    """The newest run directory carrying a stored entrypoint."""
    root = results_dir or (EXPERIMENT_DIR / "results")
    candidates = sorted(
        (d for d in root.iterdir() if (d / "results.json").exists()),
        reverse=True,
    )
    for d in candidates:
        payload = json.loads((d / "results.json").read_text(encoding="utf-8"))
        if (payload.get("entrypoint_function") or {}).get("implementation"):
            return d
    raise SystemExit(f"no run under {root} carries a stored entrypoint")


def load_entrypoint(run_dir: Path) -> tuple[Any, str]:
    """The stored function, ready to call, plus the port its URLs point at."""
    payload = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    impl = payload["entrypoint_function"]["implementation"]

    async def query_llm(prompt: str, **kwargs: Any) -> str:
        _ = kwargs
        return json.dumps(stub_narrative(prompt))

    stubs = {"query_llm": query_llm}
    namespace: dict[str, Any] = dict(stubs)
    exec(impl, namespace)  # noqa: S102 - replaying committed evidence is the point
    # The recorded name is authoritative; distilled functions are not named to
    # a convention (one run produced run_monthly_…, another generate_monthly_…).
    recorded = (payload["entrypoint_function"].get("name") or "").strip()
    fn = namespace.get(recorded)
    if not callable(fn):
        defined = [
            v
            for k, v in namespace.items()
            if callable(v) and k not in stubs and getattr(v, "__module__", None) is None
        ]
        fn = defined[0] if len(defined) == 1 else None
    if fn is None:
        raise SystemExit(
            f"cannot find the entrypoint callable in {run_dir.name} "
            f"(recorded name {recorded!r})",
        )
    ports = set(re.findall(r"127\.0\.0\.1:(\d+)", impl))
    return fn, ports.pop() if len(ports) == 1 else str(DEFAULT_PORT)


async def replay(
    *,
    seed: int,
    anchor: str,
    run_dir: Path,
) -> dict[str, Any]:
    fn, port = load_entrypoint(run_dir)
    fixture = FixtureServer(seed=seed, port=int(port), anchor=anchor).start()
    try:
        result = fn()
        if inspect.isawaitable(result):
            await result
        deliveries = fixture.sink.snapshot()
    finally:
        fixture.stop()
    return score_run(deliveries, seed=seed, anchor=anchor)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=None, help="run dir (default: newest)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--anchor", default=None, help="reported month, YYYY-MM")
    args = parser.parse_args()

    run_dir = Path(args.results) if args.results else latest_results()
    anchor = args.anchor or default_anchor()
    truth = fixture_selftest(args.seed, anchor)
    print(
        f"[fixture] month={anchor} planted={truth['flagged_campaigns']} "
        f"across {len(truth['flagged_clients'])} clients",
    )
    print(f"[replay] {run_dir.name}")
    scored = asyncio.run(
        replay(seed=args.seed, anchor=anchor, run_dir=run_dir),
    )
    print(
        f"[result] flags {scored['flags_matched_total']}/"
        f"{scored['flags_expected_total']} matched, "
        f"{scored['flags_extra_total']} extra, {scored['flags_missed_total']} missed",
    )
    print(
        f"[result] delivered {scored['clients_delivered']}/{scored['clients_total']}, "
        f"drafted {scored['reports_drafted']}, blocked {scored['reports_blocked']}",
    )
    for row in scored["clients"]:
        if row["flags_missed"] or row["flags_extra"] or row["status"] != "drafted":
            print(
                f"    {row['client_id']} {row['status']} "
                f"missed={row['flags_missed']} extra={row['flags_extra']} "
                f"{row['blocked_reason'][:70]}",
            )


if __name__ == "__main__":
    main()
