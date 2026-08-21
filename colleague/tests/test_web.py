"""Local browser host keeps the human arm explicit, scoped and measurable."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from colleague.web import (
    REFERENCE_HOURLY_RATE_USD,
    AppServer,
    BrowserRun,
    Handler,
    _validate_request,
    catalog,
)


def test_catalog_exposes_every_human_protocol_and_marks_audio_boundary():
    data = catalog()
    keys = {(item["kind"], item["id"]) for item in data["benchmarks"]}

    assert ("conversational", "inheritance") in keys
    assert ("standing", "silent_drift") in keys
    assert ("usecase", "agency_client_reporting") in keys
    callflow = next(item for item in data["benchmarks"] if item["id"] == "callflow")
    assert callflow["available"] is False
    assert "microphone" in callflow["limitation"]
    inheritance = next(
        item for item in data["benchmarks"] if item["id"] == "inheritance"
    )
    previews = {item["id"]: item["description"] for item in inheritance["scenarios"]}
    assert "document handoff" in previews["ambiguous_recipient"]
    assert "Sarah Chen" not in previews["ambiguous_recipient"]
    assert "tags" not in inheritance
    assert "modes" not in inheritance
    assert all("tags" not in item for item in inheritance["scenarios"])
    assert all("modes" not in item for item in data["benchmarks"])


def test_ambiguous_recipient_is_a_clear_handoff_without_leaking_the_answer():
    from colleague.tracks.inheritance.scenario import scenarios

    task = next(
        item
        for item in scenarios("http://fixture.invalid")
        if item["name"] == "ambiguous_recipient"
    )
    instruction = task["request"].split("\n\n")[-1]

    assert task["sender"] == "daniel"
    assert "take over Priya's open task" in instruction
    assert "Sarah" in instruction and "it" in instruction
    assert "Sarah Chen" not in instruction
    assert "weekly metrics" not in instruction.lower()


def test_request_validation_refuses_unavailable_or_unsafe_inputs():
    with pytest.raises(ValueError, match="microphone"):
        _validate_request(
            {
                "kind": "conversational",
                "benchmark": "callflow",
                "participantEmail": "person@example.com",
            },
        )
    with pytest.raises(ValueError, match="valid participant email"):
        _validate_request(
            {
                "kind": "conversational",
                "benchmark": "inheritance",
                "participantEmail": "not an email",
            },
        )


def test_browser_request_normalizes_email_and_enforces_reference_rate():
    request = {
        "kind": "conversational",
        "benchmark": "inheritance",
        "participantEmail": "  Person+Study@Example.COM ",
        "hourlyRateUsd": 999,
        "mode": "builder",
    }

    _validate_request(request)

    assert request["participantEmail"] == "person+study@example.com"
    assert "hourlyRateUsd" not in request
    assert "mode" not in request


def test_browser_run_accepts_only_one_explicit_action_per_prompt():
    run = BrowserRun(request={})
    received: list[str] = []
    reader = threading.Thread(target=lambda: received.append(run.input("human> ")))
    reader.start()
    for _ in range(100):
        if run.awaiting_input:
            break
        time.sleep(0.001)
    assert run.awaiting_input

    run.submit("/done measured")
    with pytest.raises(ValueError, match="not waiting"):
        run.submit("/done duplicate")
    reader.join(timeout=1)

    assert received == ["/done measured"]
    assert [event["type"] for event in run.events] == ["input_required", "action"]


def test_browser_snapshot_does_not_expose_internal_cost_configuration():
    run = BrowserRun(request={})
    run.emit(
        {
            "type": "cost",
            "cost": {
                "hourly_rate_usd": REFERENCE_HOURLY_RATE_USD,
                "participant_id": "person@example.com",
            },
        },
    )

    assert run.snapshot()["events"] == []


def test_http_api_requires_local_mutation_token():
    server = AppServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/api/catalog") as response:
            payload = json.load(response)
        assert payload["benchmarks"]
        with urllib.request.urlopen(f"{base}/api/config") as response:
            config = json.load(response)
        assert "hourlyRateUsd" not in config

        request = urllib.request.Request(
            f"{base}/api/runs",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        assert caught.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_browser_run_reaches_the_existing_fixture_and_exact_scorer(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("colleague.web.RESULTS_ROOT", tmp_path)
    run = BrowserRun(
        request={
            "kind": "conversational",
            "benchmark": "attribution",
            "scenario": "answer_the_asker",
            "participantEmail": "browser@example.com",
        },
    )
    run.start()
    actions = iter(
        [
            '/post /reply {"to":"bob","text":"Thursday 14:00 UTC"}',
            "/done",
        ],
    )
    deadline = time.monotonic() + 5
    while run.status in {"queued", "running"} and time.monotonic() < deadline:
        if run.awaiting_input:
            run.submit(next(actions))
        time.sleep(0.005)

    assert run.status == "complete"
    assert run.exit_code == 0
    assert run.result_path is not None
    result = json.loads(Path(run.result_path).read_text())
    assert result["scenarios"][0]["result"]["outcome"] == "pass"
    assert result["cost"]["human_hourly_rate_usd"] == REFERENCE_HOURLY_RATE_USD
    assert result["cost"]["participant_id"] == "browser@example.com"


def test_refinement_turn_carries_the_surface_and_scores_an_exact_filing(
    tmp_path,
    monkeypatch,
):
    """The runner hands the scenario's surface to the human session, and the
    command its filing form composes — typed week, column list, rows as lists
    in cell order with a real boolean — satisfies the unchanged scorer."""
    from colleague.tracks.refinement.fixture import (
        DEFAULT_SEED,
        expected_columns,
        expected_rows,
        expected_title,
    )

    monkeypatch.setattr("colleague.web.RESULTS_ROOT", tmp_path)
    run = BrowserRun(
        request={
            "kind": "conversational",
            "benchmark": "refinement",
            "scenario": "week_2_columns",
            "participantEmail": "browser@example.com",
        },
    )
    run.start()
    filing = json.dumps(
        {
            "week": 2,
            "title": expected_title(2),
            "columns": expected_columns(2),
            "rows": expected_rows(DEFAULT_SEED, 2),
        },
    )
    actions = iter([f"/post /report {filing}", "/done"])
    deadline = time.monotonic() + 10
    while run.status in {"queued", "running"} and time.monotonic() < deadline:
        if run.awaiting_input:
            run.submit(next(actions))
        time.sleep(0.005)

    assert run.status == "complete"
    assert run.exit_code == 0
    turn = next(e for e in run.events if e.get("type") == "turn")
    surface = turn["surface"]
    assert surface and surface["actions"][0]["path"] == "/report"
    result = json.loads(Path(run.result_path).read_text())
    scored = next(
        s for s in result["scenarios"] if s["name"] == "week_2_columns"
    )
    assert scored["result"]["outcome"] == "pass"
    assert scored["result"]["detail"]["checks"]["rows_exact"] is True
