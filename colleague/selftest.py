"""Check the benchmark before checking anything with it.

Two invariants, run against the scripted mock arm so they cost nothing:

**Every scenario is winnable.** The `ideal` plan — what a competent
assistant would do — must be credited. A scenario whose ideal plan cannot
pass is unwinnable, and discovering that from a live run costs money and
produces a result that looks like a finding.

**Every scorer discriminates.** The `naive` plan — the plausible wrong
thing — must score *differently* from ideal. Not necessarily FAIL: on
`continuity` the naive behaviour reaches the right answer and pays for it,
which is exactly DEGRADED, and demanding a failure there would misrepresent
what a cold restart does. What must never happen is a scorer returning the
same verdict for both, because that scorer would report every arm as
perfect.

Deliberate exemptions are declared here rather than hidden in a scorer, so
a reader can see exactly which scenarios are calibration points rather than
tests.

    python -m colleague.selftest
"""

from __future__ import annotations

import importlib
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from colleague.harness.capability import Outcome
from colleague.harness.runner import run_track
from colleague.run import TRACKS

#: Scenarios where ideal and naive are *supposed* to agree, with the reason.
#: Exempting a scenario is a claim about the benchmark's design, so each one
#: says what it is calibrating and why an identical verdict is correct.
EXEMPT = {
    ("teaching", "untaught_control"): (
        "Establishes what the API alone yields. Unreachable without the "
        "walkthrough by construction, so UNSUPPORTED under both plans."
    ),
    ("continuity", "january"): (
        "The expensive first pass, which both plans perform identically. "
        "The measurement is the follow-up."
    ),
    ("custody", "briefing"): (
        "Setup: the facts arrive. Nothing is disclosed either way yet."
    ),
    ("custody", "asked_operational"): (
        "The disclosure control. This fact SHOULD be shared, and both plans "
        "share it — which is what proves the other two scenarios are not "
        "simply rewarding silence."
    ),
    ("custody", "second_briefing"): (
        "Setup for the late variant: more facts arrive. Nothing disclosed yet."
    ),
    ("custody", "standing_rule"): (
        "Setup: a rule is stated. Both plans stay silent; the rule is scored "
        "later, in rule_applied_late."
    ),
    ("custody", "intervening_work"): (
        "The long stretch of unrelated work that separates the late asks from "
        "the notes. Both plans do the work; the measurement is what survives it."
    ),
    ("custody", "late_asked_operational"): (
        "The late disclosure control. This fact SHOULD be shared after the "
        "intervening work, and both plans share it."
    ),
    **{
        ("recall", f"day_{i}"): (
            "A day's messages arrive. Nothing is asked; both plans listen."
        )
        for i in range(1, 9)
    },
    ("recall", "ask_portal_manager"): (
        "Retention control: a fact that was never replaced. Both plans recall "
        "it, which is what shows a wrong answer elsewhere is a stale recall "
        "rather than forgetting."
    ),
    ("recall", "ask_travel_code"): ("Retention control, as above."),
    ("recall", "ask_priya_cover"): ("Retention control, as above."),
    ("recall", "ask_board_and_bucket"): (
        "Retention control with two facts from two days in one question."
    ),
    ("membership", "briefing"): (
        "Setup: the facts arrive in their places. Nothing is disclosed yet."
    ),
    ("membership", "finance_asks_finance"): (
        "Disclosure control: a member asks about their own team's fact, and "
        "both plans answer. Proves the withholding scenarios do not reward "
        "silence."
    ),
    ("membership", "platform_asks_platform"): (
        "Disclosure control, the other team. Both plans answer."
    ),
    ("membership", "anyone_asks_general"): (
        "Disclosure control for the org-wide channel. Both plans answer."
    ),
    ("membership", "boss_asks_all"): (
        "Disclosure control from the top: the boss is in every place the "
        "facts were said. Both plans tell him everything."
    ),
}


def _run(track: str, mode: str, tmp: Path) -> dict[str, str]:
    fixture = importlib.import_module(f"colleague.tracks.{track}.fixture")
    scenario = importlib.import_module(f"colleague.tracks.{track}.scenario")
    buf = io.StringIO()
    with redirect_stdout(buf):
        run_track(
            track=track,
            arm="mock",
            fixture_module=fixture,
            scenario_module=scenario,
            results_root=tmp / track / mode,
            port=0,
            timeout_s=120,
            mode=mode,
        )
    import json

    run_dir = next((tmp / track / mode).iterdir())
    data = json.loads((run_dir / "results.json").read_text())
    return {s["name"]: s["result"]["outcome"] for s in data["scenarios"]}


def main() -> int:
    failures: list[str] = []
    with TemporaryDirectory() as raw:
        tmp = Path(raw)
        for track in TRACKS:
            ideal = _run(track, "ideal", tmp)
            naive = _run(track, "naive", tmp)
            for name, outcome in ideal.items():
                if (track, name) in EXEMPT:
                    continue
                if not Outcome(outcome).credited:
                    failures.append(
                        f"{track}/{name}: ideal plan scored {outcome} — "
                        "scenario may be unwinnable",
                    )
                if naive.get(name) == outcome:
                    failures.append(
                        f"{track}/{name}: ideal and naive both scored "
                        f"{outcome} — scorer does not discriminate",
                    )
            scored = len([n for n in ideal if (track, n) not in EXEMPT])
            exempt = len(ideal) - scored
            suffix = f", {exempt} calibration" if exempt else ""
            print(f"{track:14s} {scored} scenarios{suffix}")

    if failures:
        print("\nSELF-TEST FAILURES:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nall tracks: every scenario winnable, every scorer discriminating")
    return 0


if __name__ == "__main__":
    sys.exit(main())
