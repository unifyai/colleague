"""The persona engine: labels, memory, the leak guard, and the loop.

These tests never call a model. The llm path is exercised by stubbing the
one HTTP method (`PersonaPool._call`), so the structured-reply parsing, the
label taxonomy, memory accumulation, per-scenario evidence windows, the
leak guard's introduce-vs-echo rule, and the runner's conversation loop are
all pinned deterministically — the same way the scripted implementation
pins the self-test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from colleague.harness.conversation import Participant
from colleague.harness.persona import (
    LABELS,
    Persona,
    PersonaPool,
    asks,
    attended,
)
from colleague.harness.runner import _persona_conversation
from colleague.harness.session import Reply

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="boss",
    email="daniel@northwind.example",
)


def _pool(**persona_kwargs: Any) -> PersonaPool:
    defaults: dict[str, Any] = {
        "participant": DANIEL,
        "brief": "You are Daniel.",
        "fallback": "It's all in the brief.",
        "fallback_label": "repointed",
    }
    defaults.update(persona_kwargs)
    return PersonaPool([Persona(**defaults)])


def _scripted(pool: PersonaPool) -> PersonaPool:
    pool.force_scripted()
    return pool


class _StubLLM:
    """Swap for PersonaPool._call: returns queued raw model outputs."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, persona: Persona, message: str, channel: str):
        self.calls.append((message, channel))
        return self.outputs.pop(0), 7


# ------------------------------------------------------------------ scripted


def test_scripted_clarification_returns_fallback_with_label() -> None:
    pool = _scripted(_pool())
    pool.begin_scenario("s1")
    reply = pool.reply("daniel", "Which columns?", channel="clarification")
    assert reply.text == "It's all in the brief."
    assert reply.label == "repointed"
    assert reply.mode == "scripted"
    assert pool.exchanges()[0]["label"] == "repointed"


def test_scripted_channel_traffic_is_silent() -> None:
    pool = _scripted(_pool())
    pool.begin_scenario("s1")
    reply = pool.reply("daniel", "Filed the week 2 report.", channel="chat")
    assert reply.label == "silent"
    assert not reply.deliverable


def test_unknown_persona_answers_not_the_right_person() -> None:
    pool = _scripted(_pool())
    assert "not the right person" in pool.answer("nobody", "hello?")


# ----------------------------------------------------------------- llm path


def test_llm_reply_parses_label_and_accumulates_memory(monkeypatch) -> None:
    pool = _pool()
    stub = _StubLLM([json.dumps({"label": "restated", "reply": "Columns are v, c."})])
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool.begin_scenario("s1")
    reply = pool.reply("daniel", "Which columns?", channel="message")
    assert reply.label == "restated"
    assert reply.text == "Columns are v, c."
    assert reply.tokens == 7
    memory = pool.personas["daniel"].memory
    assert memory[-2]["role"] == "assistant"
    assert memory[-1]["role"] == "self"
    assert memory[-1]["text"] == "Columns are v, c."


def test_llm_unparsable_reply_retries_then_prices_conservatively(
    monkeypatch,
) -> None:
    stub = _StubLLM(["not json at all", "still not json"])
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool()
    pool.begin_scenario("s1")
    reply = pool.reply("daniel", "Which columns?", channel="clarification")
    # Conservative direction: an unlabelled reply can never smuggle a spec
    # re-supply past the DEGRADED pricing.
    assert reply.label == "restated"
    assert reply.mode == "label_unparsed"
    assert len(stub.calls) == 2


def test_llm_error_falls_back_to_scripted_answer(monkeypatch) -> None:
    def boom(self, persona, message, channel):
        raise OSError("network down")

    monkeypatch.setattr(PersonaPool, "_call", boom)
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool()
    pool.begin_scenario("s1")
    reply = pool.reply("daniel", "Which columns?", channel="clarification")
    assert reply.text == "It's all in the brief."
    assert reply.mode == "fallback_after_error"


def test_label_taxonomy_is_closed(monkeypatch) -> None:
    stub = _StubLLM(
        [json.dumps({"label": "helpful", "reply": "x"}), "garbage"],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool()
    reply = pool.reply("daniel", "hm", channel="chat")
    # An out-of-taxonomy label is an unparsable reply, not a new category.
    assert reply.label in LABELS


# --------------------------------------------------------------- leak guard


def test_leak_guard_voids_introduced_content(monkeypatch) -> None:
    stub = _StubLLM(
        [json.dumps({"label": "restated", "reply": "It converts to 3227.66."})],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool(forbidden=("3227.66",))
    pool.begin_scenario("s1")
    reply = pool.reply("daniel", "What does the USD row come to?", channel="message")
    assert reply.leaked == ["3227.66"]
    assert not reply.deliverable
    assert pool.leaks()
    # The blocking interface still returns something contentless.
    assert "3227.66" not in pool.answer("daniel", "What does it come to?")


def test_leak_guard_ignores_echo_of_arm_content(monkeypatch) -> None:
    stub = _StubLLM(
        [json.dumps({"label": "conversational", "reply": "Yes, 3227.66 - noted."})],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool(forbidden=("3227.66",))
    pool.begin_scenario("s1")
    reply = pool.reply("daniel", "I computed 3227.66 for that row.", channel="message")
    assert reply.leaked == []
    assert not pool.leaks()


def test_leak_guard_grouped_tokens_only_count_together(monkeypatch) -> None:
    stub = _StubLLM(
        [
            json.dumps({"label": "conversational", "reply": "See you Thursday!"}),
            json.dumps(
                {"label": "restated", "reply": "It's Thursday at 14:00, as I said."},
            ),
        ],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool(forbidden=(("thursday", "14:00"),))
    pool.begin_scenario("s1")
    assert pool.reply("daniel", "When shall we sync?", channel="message").leaked == []
    assert pool.reply("daniel", "When is the deploy?", channel="message").leaked


# ----------------------------------------------- scenario windows, overrides


def test_evidence_reports_scenario_window_not_whole_run() -> None:
    pool = _scripted(_pool())
    pool.begin_scenario("week_2")
    pool.answer("daniel", "Which columns?")
    assert len(pool.evidence()["persona_exchanges"]) == 1
    pool.begin_scenario("week_3")
    assert pool.evidence()["persona_exchanges"] == []
    assert len(pool.transcript()) == 1


def test_overrides_replace_brief_and_mask_memory() -> None:
    pool = _scripted(_pool())
    pool.note_authored("daniel", "columns are vendor, category")
    pool.begin_scenario("control")
    pool.apply_overrides(
        {
            "daniel": {
                "brief": "You never gave a brief.",
                "fallback": "No format in mind.",
                "fallback_label": "no_information",
                "fresh_memory": True,
            },
        },
    )
    reply = pool.reply("daniel", "What format?", channel="clarification")
    assert reply.text == "No format in mind."
    assert reply.label == "no_information"
    pool.apply_overrides(None)
    reply = pool.reply("daniel", "What format?", channel="clarification")
    assert reply.text == "It's all in the brief."


def test_ledger_writes_one_line_per_exchange(tmp_path: Path) -> None:
    pool = _scripted(_pool())
    pool.bind_ledger(tmp_path / "persona_ledger.jsonl", run_id="r1")
    pool.begin_scenario("s1")
    pool.answer("daniel", "Which columns?")
    lines = (tmp_path / "persona_ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["run_id"] == "r1"
    assert row["scenario"] == "s1"
    assert row["label"] == "repointed"


# ------------------------------------------------------------ asks/attended


def test_asks_merges_channels_and_keeps_addressee_semantics() -> None:
    record = {
        "clarifications": [{"question": "Which Sarah?", "who": "daniel"}],
        "persona": [
            {
                "persona": "daniel",
                "channel": "clarification",
                "question": "Which Sarah?",
                "label": "restated",
            },
            {
                "persona": "priya",
                "channel": "message",
                "question": "Vendor contact?",
                "label": "restated",
            },
            {
                "persona": "daniel",
                "channel": "chat",
                "question": "Filed it.",
                "label": "silent",
            },
        ],
    }
    got = asks(record)
    assert [a["who"] for a in got] == ["daniel", "priya"]
    assert attended(record)
    assert not attended({"persona": [{"channel": "chat", "label": "silent"}]})


# --------------------------------------------------------- conversation loop


class _LoopSession:
    """An arm whose resume answers once, then goes quiet."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.resumed: list[tuple[str, str]] = []

    def clarifications(self) -> list[dict[str, Any]]:
        return []

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        self.resumed.append((str(sender), text))
        return Reply(text=self._replies.pop(0) if self._replies else "")


class _NoResumeSession:
    def clarifications(self) -> list[dict[str, Any]]:
        return []


class _LoopFixture:
    def __init__(self, channels: dict[str, Any] | None = None) -> None:
        self.state: dict[str, Any] = {}
        if channels is not None:
            self.state["persona_channels"] = channels
        self._entries: dict[str, list[dict[str, Any]]] = {}

    def post(self, kind: str, payload: dict[str, Any]) -> None:
        self._entries.setdefault(kind, []).append({"payload": payload})

    class _Recorder:
        def __init__(self, outer: "_LoopFixture") -> None:
            self._outer = outer

        def all(self, kind: str | None = None):
            if kind is None:
                return [e for v in self._outer._entries.values() for e in v]
            return list(self._outer._entries.get(kind, []))

    @property
    def recorder(self) -> "_LoopFixture._Recorder":
        return self._Recorder(self)


def test_loop_answers_a_question_asked_in_the_reply(monkeypatch) -> None:
    """The motivating incident: a cold arm asks Daniel in its reply text."""
    stub = _StubLLM(
        [
            json.dumps(
                {"label": "restated", "reply": "The source is /expenses?week=2."},
            ),
            json.dumps({"label": "silent", "reply": ""}),
        ],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool()
    pool.begin_scenario("s1")
    session = _LoopSession(replies=["Filed the report - thanks."])
    journal: list[dict[str, Any]] = []
    final = _persona_conversation(
        session=session,
        fixture=_LoopFixture(),
        pool=pool,
        counterpart="daniel",
        reply=Reply(text="I can't find the Week 2 expense source - please share."),
        journal=journal,
    )
    assert session.resumed == [("daniel", "The source is /expenses?week=2.")]
    assert final.text == "Filed the report - thanks."
    assert journal[0]["label"] == "restated"
    assert journal[0]["delivered"] is True


def test_loop_routes_bridged_channel_traffic(monkeypatch) -> None:
    stub = _StubLLM(
        [
            json.dumps({"label": "restated", "reply": "Vendor, category - as given."}),
            json.dumps({"label": "silent", "reply": ""}),
            json.dumps({"label": "silent", "reply": ""}),
        ],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool()
    pool.begin_scenario("s1")
    fixture = _LoopFixture(channels={"reply": {"who": "to", "text": "text"}})
    fixture.post("reply", {"to": "daniel", "text": "What were the columns again?"})
    session = _LoopSession(replies=["Done."])
    journal: list[dict[str, Any]] = []
    _persona_conversation(
        session=session,
        fixture=fixture,
        pool=pool,
        counterpart="daniel",
        reply=Reply(text=""),
        journal=journal,
    )
    assert session.resumed[0][0] == "daniel"
    assert "Vendor, category" in session.resumed[0][1]


def test_loop_scripted_mode_is_inert_for_chat(monkeypatch) -> None:
    pool = _scripted(_pool())
    pool.begin_scenario("s1")
    session = _LoopSession(replies=[])
    journal: list[dict[str, Any]] = []
    final = _persona_conversation(
        session=session,
        fixture=_LoopFixture(),
        pool=pool,
        counterpart="daniel",
        reply=Reply(text="Where is the source?"),
        journal=journal,
    )
    assert session.resumed == []
    assert journal == []
    assert final.text == "Where is the source?"


def test_loop_leaked_reply_is_not_delivered(monkeypatch) -> None:
    stub = _StubLLM(
        [json.dumps({"label": "restated", "reply": "It comes to 3227.66."})],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool(forbidden=("3227.66",))
    pool.begin_scenario("s1")
    session = _LoopSession(replies=[])
    journal: list[dict[str, Any]] = []
    _persona_conversation(
        session=session,
        fixture=_LoopFixture(),
        pool=pool,
        counterpart="daniel",
        reply=Reply(text="What does the USD row convert to?"),
        journal=journal,
    )
    assert session.resumed == []
    assert journal[0].get("leaked") is True
    assert pool.leaks()


def test_loop_no_resume_path_records_undeliverable(monkeypatch) -> None:
    stub = _StubLLM([json.dumps({"label": "restated", "reply": "Answer."})])
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool()
    pool.begin_scenario("s1")
    journal: list[dict[str, Any]] = []
    _persona_conversation(
        session=_NoResumeSession(),
        fixture=_LoopFixture(),
        pool=pool,
        counterpart="daniel",
        reply=Reply(text="Where is it?"),
        journal=journal,
    )
    assert journal[0]["delivery"] == "no_resume_path"
    assert journal[0]["delivered"] is False


def test_loop_round_cap_holds(monkeypatch) -> None:
    stub = _StubLLM(
        [json.dumps({"label": "restated", "reply": f"Answer {i}."}) for i in range(20)],
    )
    monkeypatch.setattr(PersonaPool, "_call", lambda self, p, m, c: stub(p, m, c))
    monkeypatch.setattr(PersonaPool, "live", property(lambda self: True))
    pool = _pool()
    pool.begin_scenario("s1")
    session = _LoopSession(replies=[f"And question {i}?" for i in range(20)])
    journal: list[dict[str, Any]] = []
    _persona_conversation(
        session=session,
        fixture=_LoopFixture(),
        pool=pool,
        counterpart="daniel",
        reply=Reply(text="Question 0?"),
        journal=journal,
    )
    from colleague.harness.runner import PERSONA_ROUNDS

    assert len(session.resumed) == PERSONA_ROUNDS


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
