"""Check the benchmark before checking anything with it.

First the taxonomy: every scenario, experiment and page carries a complete
tag set in `colleague/taxonomy.py` and no entry is stale, so a new cell
cannot land uncategorised and the categories cannot drift from the suite.

Then two invariants, run against the scripted mock arm so they cost nothing:

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

The `standing` fire-series experiments are checked the same way through
their own scripted arm, under three plans instead of two — `ideal`, `naive`
and `held` — because their rubric has three rungs: every fire of the ideal
plan must score *correct*, the naive plan must produce at least one *wrong*
fire and never outscore ideal, and the held plan must reach the middle rung
at least once. A rubric whose middle rung no plan can reach is decoration.

    python -m colleague.selftest
"""

from __future__ import annotations

import importlib
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from colleague import taxonomy
from colleague.harness.capability import Outcome
from colleague.harness.runner import run_track
from colleague.run import TRACKS
from colleague.tracks.standing.series import mock_arm
from colleague.tracks.standing.series.spec import CORRECT, HELD, WRONG, Experiment

#: Scenarios where ideal and naive are *supposed* to agree, with the reason.
#: Exempting a scenario is a claim about the benchmark's design, so each one
#: says what it is calibrating and why an identical verdict is correct.
EXEMPT = {
    ("teaching", "untaught_control"): (
        "Establishes what the API alone yields. Unreachable without the "
        "walkthrough by construction, so UNSUPPORTED under both plans."
    ),
    ("refinement", "week_1_briefed"): (
        "The pre-spec first pass: the brief fixes no format, so both plans "
        "file the obvious draft and only filing is scored. The feedback "
        "that fixes the format is the next scenario, and the measurement "
        "is every later week."
    ),
    ("refinement", "unbriefed_control"): (
        "Establishes what the API alone yields. The exact format is not "
        "discoverable without the brief by construction, so UNSUPPORTED "
        "under both plans."
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


def _check_taxonomy() -> list[str]:
    """Every cell categorised, every category real, roles consistent.

    Three invariants beyond `taxonomy.check_entries`: each track's scenario
    list and its taxonomy entries match exactly (nothing uncategorised,
    nothing stale); every `standing` experiment and `usecases` page has an
    entry; and every selftest exemption is a `feed` or `control` cell —
    an exempt probe would be a scored question whose scorer is never
    checked for discrimination.
    """
    problems = taxonomy.check_entries()
    for track in TRACKS:
        scenario = importlib.import_module(f"colleague.tracks.{track}.scenario")
        names = [s["name"] for s in scenario.scenarios("http://x")]
        problems += taxonomy.check_track(track, names)

    from colleague.human import SERIES
    from colleague.tracks.standing.human_legacy import RUNNERS as LEGACY
    from colleague.tracks.usecases.human import RUNNERS as USECASES

    problems += taxonomy.check_track("standing", {*SERIES, *LEGACY})
    problems += taxonomy.check_track("usecases", USECASES)

    for track, name in EXEMPT:
        tags = taxonomy.tags_for(track, name)
        if tags is not None and tags.role == "probe":
            problems.append(
                f"{track}/{name}: exempt from discrimination checks but "
                "tagged as a probe — a probe's scorer must discriminate",
            )
    counts: dict[str, int] = {}
    for (track, name), _tags in taxonomy.ALL_CELLS.items():
        slug = taxonomy.topic_of(track, name)
        counts[slug] = counts.get(slug, 0) + 1
    print(
        "taxonomy: "
        + ", ".join(
            f"{taxonomy.topic_title(slug)} {counts[slug]}"
            for slug in taxonomy.TOPICS
            if slug in counts
        ),
    )
    return problems


def _check_personas() -> list[str]:
    """Every persona well-formed before a model ever plays one.

    Briefs must exist (a persona with no brief is an unbounded
    improviser), declared labels must come from the one taxonomy, and no
    scripted fallback may carry a forbidden token — a canned answer that
    trips its own leak guard would void every scripted cell it touches.
    Scenario-level overrides are held to the same rules, and must name a
    persona that exists.
    """
    from colleague.harness.persona import LABELS

    problems: list[str] = []
    for track in TRACKS:
        fixture_module = importlib.import_module(f"colleague.tracks.{track}.fixture")
        fx = fixture_module.build(port=0)
        try:
            pool = fx.state.get("personas")
            if pool is None:
                continue
            for pid, persona in pool.personas.items():
                if not persona.brief.strip():
                    problems.append(f"{track}/{pid}: persona has no brief")
                if persona.fallback_label not in LABELS:
                    problems.append(
                        f"{track}/{pid}: fallback_label "
                        f"{persona.fallback_label!r} is not in the taxonomy",
                    )
                blob = (persona.fallback or "").lower()
                for entry in persona.forbidden:
                    parts = entry if isinstance(entry, tuple) else (entry,)
                    if all(p.lower() in blob for p in parts):
                        problems.append(
                            f"{track}/{pid}: scripted fallback contains "
                            f"forbidden content {entry!r}",
                        )
            scenario_module = importlib.import_module(
                f"colleague.tracks.{track}.scenario",
            )
            for spec in scenario_module.scenarios("http://x"):
                for who, override in (spec.get("persona_overrides") or {}).items():
                    where = f"{track}/{spec['name']}/{who}"
                    if who not in pool.personas:
                        problems.append(
                            f"{where}: override names a persona that "
                            "does not exist",
                        )
                    label = override.get("fallback_label")
                    if label is not None and label not in LABELS:
                        problems.append(
                            f"{where}: fallback_label {label!r} is not in "
                            "the taxonomy",
                        )
                    blob = str(override.get("fallback") or "").lower()
                    for entry in override.get("forbidden", ()):
                        parts = entry if isinstance(entry, tuple) else (entry,)
                        if all(p.lower() in blob for p in parts):
                            problems.append(
                                f"{where}: scripted fallback contains "
                                f"forbidden content {entry!r}",
                            )
        finally:
            fx.stop()
    return problems


def series_experiments() -> list[Experiment]:
    """Every fire-series experiment and variant, as the drivers would build it."""
    from colleague.tracks.standing.change_without_regression.protocol import (
        ChangeWithoutRegression,
    )
    from colleague.tracks.standing.drift_recovery.protocol import DriftRecovery
    from colleague.tracks.standing.edge_week.fixture import VARIANTS as EDGES
    from colleague.tracks.standing.edge_week.protocol import EdgeWeek
    from colleague.tracks.standing.repair_locality.protocol import RepairLocality
    from colleague.tracks.standing.silent_drift.fixture import VARIANTS as DRIFTS
    from colleague.tracks.standing.silent_drift.protocol import SilentDrift

    return [
        DriftRecovery(),
        *[SilentDrift(v) for v in DRIFTS],
        *[EdgeWeek(v) for v in EDGES],
        RepairLocality(),
        ChangeWithoutRegression(),
    ]


def _check_series(experiment: Experiment) -> list[str]:
    scores = {
        mode: [int(r["score"]) for r in mock_arm.run(experiment, mode=mode)["fires"]]
        for mode in mock_arm.MODES
    }
    label = f"standing/{experiment.name}" + (
        f"[{experiment.variant()}]" if experiment.variant() else ""
    )
    failures: list[str] = []
    if any(s != CORRECT for s in scores["ideal"]):
        failures.append(
            f"{label}: ideal plan scored {scores['ideal']} — a fire is unwinnable",
        )
    if WRONG not in scores["naive"]:
        failures.append(
            f"{label}: naive plan never scored wrong {scores['naive']} — scorer does not discriminate",
        )
    if any(n > i for n, i in zip(scores["naive"], scores["ideal"])):
        failures.append(f"{label}: naive outscored ideal on a fire {scores['naive']}")
    if HELD not in scores["held"]:
        failures.append(
            f"{label}: held plan never scored held {scores['held']} — the middle rung is unreachable",
        )
    if len({tuple(v) for v in scores.values()}) != 3:
        failures.append(f"{label}: two plans scored identically {scores}")
    n = len(scores["ideal"])
    print(
        f"{label:44s} {n} fires: "
        + ", ".join(f"{m} {sum(v)}/{CORRECT * n}" for m, v in scores.items()),
    )
    return failures


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
    failures: list[str] = _check_taxonomy()
    failures += _check_personas()
    print()
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

    print()
    for experiment in series_experiments():
        failures.extend(_check_series(experiment))

    if failures:
        print("\nSELF-TEST FAILURES:")
        for f in failures:
            print(f"  {f}")
        return 1
    print(
        "\nall tracks: every scenario winnable, every scorer discriminating, "
        "every cell categorised; "
        "every fire series: ideal correct, naive wrong, held reachable",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
