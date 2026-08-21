"""Local browser host keeps the human arm explicit, scoped and measurable."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from colleague.web import AppServer, BrowserRun, Handler, _validate_request, catalog


def test_catalog_exposes_every_human_protocol_and_marks_audio_boundary():
    data = catalog()
    keys = {(item["kind"], item["id"]) for item in data["benchmarks"]}

    assert ("conversational", "inheritance") in keys
    assert ("standing", "silent_drift") in keys
    assert ("usecase", "agency_client_reporting") in keys
    callflow = next(item for item in data["benchmarks"] if item["id"] == "callflow")
    assert callflow["available"] is False
    assert "microphone" in callflow["limitation"]


def test_request_validation_refuses_unavailable_or_unsafe_inputs():
    with pytest.raises(ValueError, match="microphone"):
        _validate_request(
            {
                "kind": "conversational",
                "benchmark": "callflow",
                "participantId": "p1",
                "hourlyRateUsd": 30,
            },
        )
    with pytest.raises(ValueError, match="pseudonymous"):
        _validate_request(
            {
                "kind": "conversational",
                "benchmark": "inheritance",
                "participantId": "A Person",
                "hourlyRateUsd": 30,
            },
        )


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


def test_http_api_requires_local_mutation_token():
    server = AppServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/api/catalog") as response:
            payload = json.load(response)
        assert payload["benchmarks"]

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
            "mode": "participant",
            "participantId": "p-browser",
            "hourlyRateUsd": 36,
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
