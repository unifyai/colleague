"""A scripted arm for the fire-series experiments — the self-test path.

Runs an experiment's own ``mock_fire`` plan against the live fixture over
HTTP, under three modes:

    ideal   what a competent automation does — every fire should score 2
    naive   the plausible wrong thing — the measured fires should score 0
    held    the safe stop — the measured fires should score 1

The three together prove what a live run cannot: that the scenario is
winnable, that the scorer can tell wrong from right, and that the rubric's
middle rung is reachable. No LLM is involved and nothing here is a result.
"""

from __future__ import annotations

from typing import Any

from colleague.arms.sessions.mock_session import Client
from colleague.tracks.standing.series.report import attach_fire_tokens
from colleague.tracks.standing.series.spec import Experiment, messages_since

MODES = ("ideal", "naive", "held")


def run(
    experiment: Experiment,
    *,
    mode: str,
    seed: int | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    fixture = experiment.build_fixture(
        seed=seed if seed is not None else experiment.default_seed,
        port=0,
    ).start()
    client = Client(fixture.base_url)
    memory: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    try:
        for i in range(1, experiment.n_fires + 1):
            events = experiment.before_fire(fixture, i)
            for text in experiment.operator_messages(i, fixture.base_url):
                experiment.mock_operator_message(
                    memory=memory,
                    i=i,
                    text=text,
                    mode=mode,
                )
            ctx = experiment.prepare_fire(fixture)
            ctx["fire"] = i
            owner_before = len(fixture.state["owner"])
            experiment.mock_fire(
                client=client,
                fixture=fixture,
                i=i,
                mode=mode,
                memory=memory,
            )
            rows.append(
                {
                    "fire": i,
                    "label": experiment.label(i),
                    "events": events,
                    **experiment.score_fire(
                        fixture,
                        ctx,
                        messages=messages_since(fixture, owner_before),
                    ),
                },
            )
    finally:
        fixture.stop()
    attach_fire_tokens(rows, [], experiment)
    return {
        "experiment": experiment.name,
        "variant": experiment.variant(),
        "system": f"mock-{mode}",
        "fires": rows,
        "series": experiment.summarize(rows),
    }


def hold(client: Client, why: str) -> None:
    """What every scripted plan does to hold: tell the owner, deliver nothing."""
    client.post("/owner/notify", {"message": f"HOLD: {why}"})
