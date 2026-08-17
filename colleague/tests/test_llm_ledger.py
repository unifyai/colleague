"""Regression tests for LLM metering.

The ledger reports what a benchmark run cost, and a run costs real money, so
the failure that matters is not a crash — it is the ledger recording nothing
and reporting $0, which reads as a free run rather than a missing measurement.
That happened three times: `LLMEvent` dropped a field the ledger read, unillm's
listener isolation swallowed the resulting AttributeError on every event, and
the phase table came out empty.

These tests drive the ledger through the real unillm emit path — main thread,
worker thread, and a fresh event loop, matching how the runtime actually makes
calls — and pin the two properties that make a repeat visible: drift fails at
install time, and lost events are reported rather than shown as zero.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

unillm = pytest.importorskip("unillm")
pytest.importorskip("unify.common.llm_client")

from unify.common.llm_client import tag_origin_with_purpose  # noqa: E402
from unillm.llm_events import LLMEvent, _emit_llm_event  # noqa: E402

from colleague.harness.llm_ledger import LLMLedger  # noqa: E402


@pytest.fixture(autouse=True)
def clean_listeners():
    unillm.clear_llm_event_listeners()
    yield
    unillm.clear_llm_event_listeners()


def _completion(
    model: str = "openai/gpt-5.6-terra@openrouter",
    cost: float = 0.25,
    origin: str | None = None,
):
    """An event shaped like the ones the client emits after a completion."""
    return LLMEvent(
        request={"model": model},
        response={
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        },
        provider_cost=cost,
        origin=origin,
    )


@pytest.fixture
def ledger():
    led = LLMLedger()
    led.install()
    yield led
    led.uninstall()


class TestRecordingThroughRealCallPaths:
    """The ledger must see every call the runtime can make."""

    def test_records_a_completion(self, ledger):
        _emit_llm_event(_completion())

        segments = ledger.summarize()
        assert sum(s.llm_calls for s in segments) == 1
        assert sum(s.provider_cost for s in segments) == pytest.approx(0.25)
        assert sum(s.total_tokens for s in segments) == 120

    def test_records_a_call_made_on_a_worker_thread(self, ledger):
        """Managers dispatch work with asyncio.to_thread, so events arrive from
        threads that never touched the ledger."""
        thread = threading.Thread(target=lambda: _emit_llm_event(_completion()))
        thread.start()
        thread.join()

        assert sum(s.llm_calls for s in ledger.summarize()) == 1

    def test_records_a_call_made_on_a_fresh_event_loop(self, ledger):
        """`execute_code` runs plans in-process, and a nested asyncio.run builds
        a loop that did not exist when the ledger was installed. Per-loop state
        would lose these; a process-global registry does not."""

        async def emit():
            _emit_llm_event(_completion())

        asyncio.run(emit())
        asyncio.run(emit())

        assert sum(s.llm_calls for s in ledger.summarize()) == 2

    def test_attributes_calls_to_the_phase_they_landed_in(self, ledger):
        with ledger.phase("setup"):
            _emit_llm_event(_completion(cost=1.0))
        with ledger.phase("run_1"):
            _emit_llm_event(_completion(cost=2.0))
            _emit_llm_event(_completion(cost=3.0))

        by_name = {s.name: s for s in ledger.summarize()}
        assert by_name["setup"].llm_calls == 1
        assert by_name["setup"].provider_cost == pytest.approx(1.0)
        assert by_name["run_1"].llm_calls == 2
        assert by_name["run_1"].provider_cost == pytest.approx(5.0)

    def test_splits_a_phase_by_the_purpose_unify_tagged_on_the_origin(self, ledger):
        """A fire's spend reads as planning / verification / repair from the
        client tag; an untagged call is planning, which is also what every
        proxy-metered arm reports."""
        with ledger.phase("fire_5"):
            _emit_llm_event(_completion(origin="CodeActActor.act"))
            _emit_llm_event(
                _completion(
                    origin=tag_origin_with_purpose("Verifier.args", "verification"),
                ),
            )
            _emit_llm_event(
                _completion(
                    origin=tag_origin_with_purpose("Verifier.post", "verification"),
                ),
            )
            _emit_llm_event(
                _completion(origin=tag_origin_with_purpose("Repair", "repair")),
            )

        fire = {s.name: s for s in ledger.summarize()}["fire_5"].to_json()
        assert fire["llm_calls"] == 4
        assert fire["by_purpose"]["planning"] == {
            "llm_calls": 1,
            "prompt_tokens": 100,
            "completion_tokens": 20,
        }
        assert fire["by_purpose"]["verification"]["llm_calls"] == 2
        assert fire["by_purpose"]["repair"]["prompt_tokens"] == 100
        total = sum(
            b["prompt_tokens"] + b["completion_tokens"]
            for b in fire["by_purpose"].values()
        )
        assert total == fire["total_tokens"]


class TestCoexistenceWithTheRuntimesOwnListener:
    """Metering must not depend on winning a race against unify.init()."""

    def test_ledger_and_a_prior_listener_both_receive_events(self):
        """unify.init() registers its EventBus listener; the ledger registers
        after it. Neither may displace the other, in either order."""
        runtime_events: list[LLMEvent] = []
        unillm.add_llm_event_listener(runtime_events.append)

        led = LLMLedger()
        led.install()
        try:
            _emit_llm_event(_completion())

            assert sum(s.llm_calls for s in led.summarize()) == 1
            assert len(runtime_events) == 1
        finally:
            led.uninstall()

    def test_a_later_listener_does_not_displace_the_ledger(self):
        led = LLMLedger()
        led.install()
        try:
            late_events: list[LLMEvent] = []
            unillm.add_llm_event_listener(late_events.append)

            _emit_llm_event(_completion())

            assert sum(s.llm_calls for s in led.summarize()) == 1
            assert len(late_events) == 1
        finally:
            led.uninstall()

    def test_a_scoped_hook_does_not_blind_the_ledger(self):
        """A scoped capture anywhere in the call path used to take precedence
        over process-wide metering, silently unmetering that stretch."""
        led = LLMLedger()
        led.install()
        try:
            scoped: list[LLMEvent] = []
            with unillm.llm_event_hook_scope(scoped.append):
                _emit_llm_event(_completion())

            assert sum(s.llm_calls for s in led.summarize()) == 1
            assert len(scoped) == 1
        finally:
            led.uninstall()

    def test_uninstall_leaves_other_listeners_registered(self):
        runtime_events: list[LLMEvent] = []
        unillm.add_llm_event_listener(runtime_events.append)

        led = LLMLedger()
        led.install()
        led.uninstall()

        _emit_llm_event(_completion())

        assert sum(s.llm_calls for s in led.summarize()) == 0
        assert len(runtime_events) == 1


class TestDriftFailsLoudly:
    """The bug that lost three runs, and why it cannot repeat silently."""

    def test_install_refuses_when_the_record_path_raises(self):
        """A ledger reading a field LLMEvent no longer carries must fail at
        install, not after a paid run has produced an empty cost table."""

        class StaleLedger(LLMLedger):
            def _on_event(self, event: LLMEvent) -> None:
                # `billed_cost` was removed from LLMEvent; reading it is the
                # exact drift that silently zeroed three runs.
                _ = event.billed_cost

        with pytest.raises(RuntimeError, match="metering is broken"):
            StaleLedger().install()

    def test_a_refused_install_registers_nothing(self):
        class StaleLedger(LLMLedger):
            def _on_event(self, event: LLMEvent) -> None:
                _ = event.billed_cost

        with pytest.raises(RuntimeError):
            StaleLedger().install()

        assert unillm.llm_event_listeners() == ()

    def test_install_self_test_leaves_no_record_behind(self):
        led = LLMLedger()
        led.install()
        try:
            assert sum(s.llm_calls for s in led.summarize()) == 0
        finally:
            led.uninstall()

    def test_install_self_test_does_not_pollute_captured_requests(self, tmp_path):
        """Captured requests feed offline replay, so the probe must not appear
        among them."""
        capture = tmp_path / "requests.jsonl"
        led = LLMLedger(capture_requests_path=capture)
        led.install()
        try:
            assert not capture.exists()
            _emit_llm_event(_completion())
            assert capture.read_text().count("\n") == 1
            assert "metering-self-test" not in capture.read_text()
        finally:
            led.uninstall()

    def test_lost_events_are_reported_rather_than_shown_as_zero(self, ledger):
        """An event the ledger could not record must surface as a fault.

        Isolation means a raising callback records nothing. Without the fault,
        the resulting empty table is indistinguishable from a run that made no
        calls at all.
        """
        # A request that is neither a mapping nor empty makes the record path
        # raise, standing in for any event shape the ledger cannot handle.
        _emit_llm_event(LLMEvent(request=["malformed"]))

        assert sum(s.llm_calls for s in ledger.summarize()) == 0
        fault = ledger.metering_fault()
        assert fault is not None and "lost" in fault
        with pytest.raises(RuntimeError, match="metering is unreliable"):
            ledger.require_metering()

    def test_an_uninstalled_ledger_reports_a_fault(self):
        """Zero calls from a ledger that was never installed is a missing
        measurement, not a free run."""
        led = LLMLedger()

        assert led.metering_fault() is not None
        with pytest.raises(RuntimeError, match="metering is unreliable"):
            led.require_metering()

    def test_a_healthy_ledger_reports_no_fault(self, ledger):
        _emit_llm_event(_completion())

        assert ledger.metering_fault() is None
        ledger.require_metering()
