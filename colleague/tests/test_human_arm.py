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
