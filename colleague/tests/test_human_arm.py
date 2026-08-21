"""The human arm must remain measurable without smuggling in answers."""

from __future__ import annotations

import io
import json
import time
from collections import deque

import pytest

from colleague.aggregate import merge, to_markdown
from colleague.arms.sessions import AUTOMATED_ARMS
from colleague.arms.sessions.human_session import HumanSession
from colleague.harness.cost import delta, total
from colleague.harness.ledger import PhaseLedger
from colleague.harness.llm_ledger import LLMCallRecord, PhaseStats
from colleague.plan import _resolve_arms
from colleague.tracks.attribution.fixture import build
from colleague.tracks.standing.drift_recovery.protocol import UTTERANCE_TEMPLATE
from colleague.tracks.standing.human_brief import direct_work_brief


def scripted(*lines: str):
    queue = deque(lines)

    def read(_prompt: str) -> str:
        return queue.popleft()

    return read


def test_human_can_act_on_the_same_fixture_contract(tmp_path):
    fixture = build(seed=1, port=0).start()
    try:
        output = io.StringIO()
        session = HumanSession(
            results_dir=tmp_path,
            participant_id="p1",
            hourly_rate_usd=36.0,
            input_fn=scripted(
                '/post /reply {"to":"bob","text":"Thursday 14:00 UTC"}',
                "/done finished",
            ),
            output=output,
        )
        session.bind_fixture(fixture, "answer_the_asker")
        reply = session.send("Answer Bob through the documented fixture.")

        assert reply.text == "finished"
        assert fixture.recorder.all("reply")[0]["payload"]["to"] == "bob"
        snap = session.cost_snapshot()
        assert snap["meter"] == "human_labor"
        assert snap["active_seconds"] > 0
        assert snap["turns"] == 1
    finally:
        fixture.stop()


def test_human_notes_persist_between_turns(tmp_path):
    session = HumanSession(
        results_dir=tmp_path,
        input_fn=scripted("/note Leeds", "/done", "/notes", "/done Leeds"),
        output=io.StringIO(),
    )
    session.send("Remember the location", persist=True)
    reply = session.resume("Where is it?")
    assert reply.text == "Leeds"
    assert session.notes_path.read_text().strip() == "Leeds"


def test_human_workbench_has_no_code_execution_command(tmp_path):
    output = io.StringIO()
    marker = tmp_path / "must-not-exist"
    session = HumanSession(
        results_dir=tmp_path,
        input_fn=scripted(f"/shell touch {marker}", "/done"),
        output=output,
    )

    session.send("Complete the task.")

    assert not marker.exists()
    assert "Unknown command" in output.getvalue()


def test_participant_surfaces_speak_office_language():
    import json
    import re

    from colleague.tracks.standing.human_brief import (
        SUMMARIES,
        policy_surfaces,
        standing_surface,
    )
    from colleague.tracks.usecases.human import _agency_surface, _ecommerce_surface

    surfaces = {
        name: standing_surface(name)
        for name in (
            "recurring_report",
            "semantic_triage",
            "drift_recovery",
            "silent_drift",
            "edge_week",
            "repair_locality",
            "change_without_regression",
        )
    }
    surfaces.update(policy_surfaces())
    surfaces["agency"] = _agency_surface("A marketing brief.")
    surfaces["ecommerce"] = _ecommerce_surface("A trading brief.")

    for name, surface in surfaces.items():
        assert surface, name
        json.dumps(surface)  # must reach the browser as-is
        brief = surface["brief"]
        for term in ("http", "GET ", "POST", "JSON", "endpoint", "API"):
            assert term not in brief, (name, term)
        # Machine field names stay in the form definitions, never the prose.
        assert not re.search(r"\b\w+_\w+\b", brief), name
    assert set(SUMMARIES) >= {
        n for n in surfaces if n not in ("triage", "digests", "audits", "agency", "ecommerce")
    }


def test_change_request_widens_the_surface_without_leaking_it_early():
    from colleague.tracks.standing.change_without_regression.protocol import (
        CHANGE_REQUEST_TEMPLATE,
    )
    from colleague.tracks.standing.human_brief import (
        human_update_request,
        standing_surface,
    )

    def keys(surface):
        return {f["key"] for f in surface["actions"][0]["fields"]}

    before = standing_surface("change_without_regression", updates=0)
    after = standing_surface("change_without_regression", updates=1)
    assert "total_refunded_cents" not in keys(before)
    assert "total_refunded_cents" in keys(after)
    assert len(after["lookups"]) == len(before["lookups"]) + 1

    rendered = human_update_request(
        "change_without_regression",
        CHANGE_REQUEST_TEMPLATE.format(base_url="http://fixture.invalid"),
    )
    assert "http" not in rendered
    assert "total_refunded_cents" not in rendered


def test_operator_fix_message_reads_naturally():
    from colleague.tracks.standing.series.spec import Experiment

    fixed = direct_work_brief(Experiment.operator_fix_message)
    assert "recurring recurring" not in fixed
    assert "automation" not in fixed.lower()


def test_recurring_brief_describes_direct_work_without_technical_setup():
    brief = direct_work_brief(
        UTTERANCE_TEMPLATE.format(
            base_url="http://fixture.invalid",
            owner_channel="Use /owner/notify if the work must be held.",
        ),
    )

    for term in ("automation", "function", "/shell", "command"):
        assert term not in brief.lower()
    assert "This work recurs hourly" in brief
    assert "/orders?after=N" in brief
    assert "total_revenue_cents" in brief
    assert "the first occurrence will be presented separately" in brief


def test_cost_delta_prices_only_measured_human_time():
    record = delta(
        {"meter": "human_labor", "active_seconds": 10, "turns": 1},
        {
            "meter": "human_labor",
            "active_seconds": 100,
            "turns": 3,
            "hourly_rate_usd": 40,
            "participant_id": "p2",
        },
        elapsed_seconds=120,
    )
    assert record["human_active_seconds"] == 90
    assert record["human_labor_cost_usd"] == pytest.approx(1.0)
    assert record["turns"] == 2
    folded = total([record, record])
    assert folded["human_active_seconds"] == 180
    assert folded["human_labor_cost_usd"] == pytest.approx(2.0)


def test_human_workbench_rejects_other_hosts(tmp_path):
    fixture = build(seed=1, port=0).start()
    try:
        session = HumanSession(results_dir=tmp_path, output=io.StringIO())
        session.bind_fixture(fixture, "scope")
        with pytest.raises(ValueError, match="only this scenario"):
            session._url("https://example.com/answer")
    finally:
        fixture.stop()


def test_proxy_phase_cost_is_null_when_any_call_lacks_a_price(tmp_path):
    ledger_path = tmp_path / "proxy.jsonl"
    rows = [
        {
            "path": "/api/v1/chat/completions",
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "usage_raw": {"cost": 0.012},
        },
        {
            "path": "/api/v1/chat/completions",
            "prompt_tokens": 3,
            "completion_tokens": 1,
            "total_tokens": 4,
            "usage_raw": {},
        },
    ]
    ledger_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    ledger = PhaseLedger(ledger_path)
    ledger.mark("run", 0, 2, 1.0)

    phase = ledger.summarize()[0]
    assert phase["provider_cost_usd"] is None
    assert phase["provider_cost_missing_calls"] == 1


def test_in_process_phase_cost_is_null_when_price_is_missing():
    stats = PhaseStats(name="run")
    stats.add(
        LLMCallRecord(
            ts=time.time(),
            model="test",
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
            provider_cost=None,
            origin=None,
            usage_raw={},
        ),
    )

    phase = stats.to_json()
    assert phase["provider_cost_usd"] is None
    assert phase["provider_cost_missing_calls"] == 1


def test_cloud_all_excludes_attached_human_but_explicit_human_is_valid():
    assert _resolve_arms("all") == list(AUTOMATED_ARMS)
    assert _resolve_arms("human") == ["human"]


def test_aggregate_reads_standing_outcomes_and_old_phase_costs():
    merged = merge(
        [
            {
                "experiment": "edge_week",
                "system": "human",
                "human_mode": "operator",
                "run_id": "human-1",
                "fires": [
                    {
                        "fire": 1,
                        "label": "week_1",
                        "correct": True,
                    },
                ],
                "cost": {
                    "meter": "human_labor",
                    "elapsed_seconds": 60,
                    "human_active_seconds": 60,
                    "human_hourly_rate_usd": 30,
                    "human_labor_cost_usd": 0.5,
                    "provider_cost_usd": None,
                },
            },
            {
                "experiment": "edge_week",
                "system": "unify",
                "run_id": "model-1",
                "fires": [{"fire": 1, "label": "week_1", "correct": False}],
                "phases": [
                    {
                        "name": "week_1",
                        "wall_seconds": 2,
                        "llm_calls": 1,
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                        "provider_cost_usd": None,
                    },
                ],
            },
        ],
    )

    assert merged["grid"]["edge_week|human-operator"]["week_1"] == ["pass"]
    assert merged["grid"]["edge_week|unify"]["week_1"] == ["fail"]
    assert merged["costs"]["unify"][0]["total_tokens"] == 12
    assert merged["costs"]["unify"][0]["provider_cost_usd"] is None
    markdown = to_markdown(merged)
    assert "| human-operator | 1 | 60.0s |" in markdown


def test_aggregate_uses_one_human_arm_for_new_results():
    merged = merge(
        [
            {
                "experiment": "policy_propagation",
                "system": "human",
                "run_id": "human-direct-1",
                "fires": [{"task": "orders", "correct": True}],
            },
        ],
    )

    assert merged["arms"] == ["human"]
    assert merged["grid"]["policy_propagation|human"]["orders"] == ["pass"]
