"""Local browser host for the human benchmark arm.

The JavaScript package in ``web/`` is deliberately a client: fixtures,
ground truth and scoring remain in Python.  This module serves the built UI
and translates browser actions into the exact commands understood by
``HumanSession``.  It binds to loopback by default because results contain
participant identifiers and the fixtures are intended only for local
benchmark runs.

    cd web && npm run build && npm start
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import mimetypes
import queue
import re
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from colleague import taxonomy
from colleague.human import SERIES
from colleague.run import TRACKS
from colleague.tracks.standing.human_brief import SUMMARIES as STANDING_SUMMARIES
from colleague.tracks.standing.human_legacy import RUNNERS as LEGACY_RUNNERS
from colleague.tracks.usecases.human import RUNNERS as USECASE_RUNNERS

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = REPO_ROOT / "web" / "dist"
RESULTS_ROOT = REPO_ROOT / "human-results"
REFERENCE_HOURLY_RATE_USD = 30.0


def _family(track: str) -> str:
    """Family headings come from the taxonomy, not a second copy of it."""
    return taxonomy.topic_title(taxonomy.TRACK_TOPICS.get(track))


QUESTIONS = {
    "inheritance": "Act on the right referent and ask the right person.",
    "interruption": "Apply a correction before the wrong action becomes final.",
    "continuity": "Carry working state into a follow-up without starting over.",
    "attribution": "Reply to the right person without leaking to anyone else.",
    "concurrency": "Keep simultaneous workstreams and corrections separate.",
    "custody": "Disclose, withhold and verify authority from fact provenance.",
    "teaching": "Learn a procedure and preserve it through later amendments.",
    "refinement": "Keep a recurring report exactly as its owner asked, week after week.",
    "membership": "Use team and channel provenance to control disclosure.",
    "recall": "Recall the current fact and reject the value it replaced.",
    "screenshare": "Reproduce demonstrated state on your own instance.",
    "meeting": "Manage the floor, timing and work requested in a group room.",
    "callflow": "Follow a decision tree on a real phone call.",
}


def _title(value: str) -> str:
    return value.replace("_", " ").title()


def catalog() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for track in TRACKS:
        scenario_module = importlib.import_module(f"colleague.tracks.{track}.scenario")
        scenarios = []
        for item in scenario_module.scenarios("http://browser-fixture.invalid"):
            voice_only = bool(item.get("voice_only"))
            scenarios.append(
                {
                    "id": item["name"],
                    # Scenario names can describe the trap they set; a
                    # participant-facing title never should.
                    "title": item.get("participant_title") or _title(item["name"]),
                    "description": item.get("participant_preview")
                    or (
                        f"A workplace scenario about how well you can "
                        f"{QUESTIONS.get(track, 'complete the requested work').lower()}"
                    ),
                    "available": not voice_only,
                    "limitation": (
                        "Requires a human audio bridge; browser text would invalidate it."
                        if voice_only
                        else None
                    ),
                },
            )
        available = any(s["available"] for s in scenarios)
        entries.append(
            {
                "kind": "conversational",
                "id": track,
                "title": _title(track),
                "family": _family(track),
                "description": QUESTIONS.get(track, ""),
                "scenarios": scenarios,
                "available": available,
                "limitation": (
                    "The callee is built, but a human microphone/speaker bridge is still pending."
                    if track == "callflow"
                    else None
                ),
            },
        )
    for name in sorted({*SERIES, *LEGACY_RUNNERS}):
        entries.append(
            {
                "kind": "standing",
                "id": name,
                "title": _title(name),
                "family": _family("standing"),
                "description": STANDING_SUMMARIES.get(
                    name,
                    "Complete recurring workplace responsibilities across several "
                    "simulated work periods.",
                ),
                "scenarios": [],
                "available": True,
                "limitation": None,
            },
        )
    for name in sorted(USECASE_RUNNERS):
        entries.append(
            {
                "kind": "usecase",
                "id": name,
                "title": _title(name),
                "family": _family("usecases"),
                "description": (
                    "Complete an end-to-end workplace workflow using realistic "
                    "records and tools."
                ),
                "scenarios": [],
                "available": True,
                "limitation": None,
            },
        )
    families = []
    ordered = [taxonomy.topic_title(slug) for slug in taxonomy.TOPICS]
    for family in dict.fromkeys([*ordered, *[e["family"] for e in entries]]):
        members = [e for e in entries if e["family"] == family]
        if members:
            families.append({"name": family, "benchmarks": members})
    return {"families": families, "benchmarks": entries}


class _NullWriter(io.TextIOBase):
    def write(self, text: str) -> int:
        return len(text)


class BrowserOutput(io.TextIOBase):
    def __init__(self, run: "BrowserRun") -> None:
        self.run = run
        self.buffer = ""
        self.lock = threading.Lock()

    def write(self, text: str) -> int:
        with self.lock:
            self.buffer += text
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                if line.strip():
                    self.run.emit({"type": "log", "text": line})
        return len(text)

    def flush(self) -> None:
        with self.lock:
            if self.buffer.strip():
                self.run.emit({"type": "log", "text": self.buffer})
            self.buffer = ""


@dataclass
class BrowserRun:
    request: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "queued"
    exit_code: int | None = None
    error: str | None = None
    result_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    awaiting_input: bool = False
    allowed_files: set[str] = field(default_factory=set)
    _commands: queue.Queue[str] = field(default_factory=queue.Queue, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _started_monotonic: float = field(default=0.0, repr=False)
    _started_wall: float = field(default=0.0, repr=False)
    _elapsed_seconds: float = field(default=0.0, repr=False)

    def start(self) -> None:
        threading.Thread(
            target=self._run,
            name=f"human-web-{self.id}",
            daemon=True,
        ).start()

    def emit(self, event: dict[str, Any]) -> None:
        item = dict(event)
        with self._lock:
            item["seq"] = len(self.events) + 1
            item["at"] = datetime.now(timezone.utc).isoformat()
            if item.get("type") == "turn":
                self.allowed_files.update(str(p) for p in item.get("images") or [])
                # Shared documents download exactly as frames serve: the turn
                # whitelists them, `/api/runs/{id}/file` refuses all else.
                self.allowed_files.update(str(p) for p in item.get("attachments") or [])
            self.events.append(item)

    def input(self, prompt: str) -> str:
        with self._lock:
            self.awaiting_input = True
        self.emit({"type": "input_required", "prompt": prompt})
        command = self._commands.get()
        with self._lock:
            self.awaiting_input = False
        self.emit({"type": "action", "command": command})
        return command

    def submit(self, command: str) -> None:
        command = command.strip("\r\n")
        if not command.startswith("/"):
            raise ValueError("actions must be explicit workbench commands")
        if len(command) > 100_000:
            raise ValueError("action is too large")
        with self._lock:
            if not self.awaiting_input:
                raise ValueError("the run is not waiting for an action")
            # Claim the prompt immediately so a double click cannot enqueue an
            # action for the following turn before the participant has seen it.
            self.awaiting_input = False
        self._commands.put(command)

    def snapshot(self, after: int = 0) -> dict[str, Any]:
        with self._lock:
            events = [
                dict(e)
                for e in self.events
                if int(e["seq"]) > after and e.get("type") != "cost"
            ]
            elapsed = self._elapsed_seconds
            if self._started_monotonic and self.status == "running":
                elapsed = time.monotonic() - self._started_monotonic
            return {
                "id": self.id,
                "request": dict(self.request),
                "status": self.status,
                "exitCode": self.exit_code,
                "error": self.error,
                "resultPath": self.result_path,
                "startedAt": self.started_at,
                "finishedAt": self.finished_at,
                "elapsedSeconds": round(elapsed, 1),
                "awaitingInput": self.awaiting_input,
                "events": events,
                "lastSeq": len(self.events),
            }

    def _run(self) -> None:
        self.status = "running"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._started_monotonic = time.monotonic()
        self._started_wall = time.time()
        self.emit({"type": "status", "status": "running"})
        output = BrowserOutput(self)
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.exit_code = self._execute(output)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the participant
            self.error = f"{type(exc).__name__}: {exc}"
            self.exit_code = 2
            self.emit({"type": "error", "text": self.error})
        finally:
            output.flush()
            self._elapsed_seconds = time.monotonic() - self._started_monotonic
            self.result_path = self._latest_result()
            self.status = "complete" if self.exit_code in (0, 1) else "error"
            self.finished_at = datetime.now(timezone.utc).isoformat()
            self.emit(
                {
                    "type": "status",
                    "status": self.status,
                    "exit_code": self.exit_code,
                    "result_path": self.result_path,
                },
            )

    def _execute(self, _output: BrowserOutput) -> int:
        kind = str(self.request["kind"])
        name = str(self.request["benchmark"])
        rate = REFERENCE_HOURLY_RATE_USD
        participant = str(self.request["participantEmail"])
        results_root = RESULTS_ROOT / kind / name
        results_root.mkdir(parents=True, exist_ok=True)
        common = {
            "hourly_rate_usd": rate,
            "participant_id": participant,
            "input_fn": self.input,
            "output": _NullWriter(),
            "event_sink": self.emit,
            "results_root": results_root,
        }
        if kind == "conversational":
            from colleague.harness.runner import run_track

            fixture = importlib.import_module(f"colleague.tracks.{name}.fixture")
            scenario = importlib.import_module(f"colleague.tracks.{name}.scenario")
            return run_track(
                track=name,
                arm="human",
                fixture_module=fixture,
                scenario_module=scenario,
                results_root=results_root,
                port=0,
                timeout_s=3600,
                only=self.request.get("scenario") or None,
                transport="text",
                human_hourly_rate_usd=rate,
                human_participant_id=participant,
                human_input_fn=self.input,
                human_output=_NullWriter(),
                human_event_sink=self.emit,
            )
        if kind == "standing" and name in LEGACY_RUNNERS:
            return LEGACY_RUNNERS[name](**common)
        if kind == "standing" and name in SERIES:
            module_name, factory = SERIES[name]
            experiment = getattr(importlib.import_module(module_name), factory)()
            from colleague.tracks.standing.series.human_arm import run

            return run(experiment, **common)
        if kind == "usecase" and name in USECASE_RUNNERS:
            return USECASE_RUNNERS[name](**common)
        raise ValueError(f"unknown benchmark {kind}/{name}")

    def _latest_result(self) -> str | None:
        root = RESULTS_ROOT / str(self.request["kind"]) / str(self.request["benchmark"])
        candidates = (
            [
                path
                for path in root.rglob("results.json")
                if path.stat().st_mtime >= self._started_wall
            ]
            if root.exists()
            else []
        )
        if not candidates:
            return None
        return str(max(candidates, key=lambda p: p.stat().st_mtime))


class RunRegistry:
    def __init__(self) -> None:
        self.runs: dict[str, BrowserRun] = {}
        self.lock = threading.Lock()

    def create(self, request: dict[str, Any]) -> BrowserRun:
        _validate_request(request)
        with self.lock:
            if any(run.status in {"queued", "running"} for run in self.runs.values()):
                raise ValueError("finish the active run before starting another")
            run = BrowserRun(request=request)
            self.runs[run.id] = run
        run.start()
        return run

    def get(self, run_id: str) -> BrowserRun:
        try:
            return self.runs[run_id]
        except KeyError as exc:
            raise KeyError("run not found") from exc


def _validate_request(value: dict[str, Any]) -> None:
    kind = value.get("kind")
    name = value.get("benchmark")
    match = next(
        (
            item
            for item in catalog()["benchmarks"]
            if item["kind"] == kind and item["id"] == name
        ),
        None,
    )
    if match is None:
        raise ValueError("unknown benchmark")
    if not match["available"]:
        raise ValueError(match.get("limitation") or "benchmark is unavailable")
    scenario = value.get("scenario")
    if scenario:
        scenario_match = next(
            (s for s in match["scenarios"] if s["id"] == scenario),
            None,
        )
        if scenario_match is None:
            raise ValueError("unknown scenario")
        if not scenario_match["available"]:
            raise ValueError(scenario_match.get("limitation") or "scenario unavailable")
    participant_email = str(value.get("participantEmail") or "").strip().lower()
    if len(participant_email) > 254 or not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+",
        participant_email,
    ):
        raise ValueError("a valid participant email address is required")

    # Browser studies use one internal reference rate for every participant.
    # Discard client-supplied values; the participant API does not expose the
    # meter configuration.
    value["participantEmail"] = participant_email
    value.pop("hourlyRateUsd", None)
    value.pop("participantId", None)
    value.pop("mode", None)


class AppServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]):
        super().__init__(address, handler)
        self.registry = RunRegistry()
        self.mutation_token = secrets.token_urlsafe(24)


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    server_version = "colleague-human-ui/1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.path == "/api/config":
            self._json(
                200,
                {
                    "mutationToken": self.server.mutation_token,
                },
            )
            return
        if parsed.path == "/api/catalog":
            self._json(200, catalog())
            return
        match = re.fullmatch(r"/api/runs/([a-f0-9]+)", parsed.path)
        if match:
            try:
                run = self.server.registry.get(match.group(1))
                after = int((parse_qs(parsed.query).get("after") or ["0"])[0])
                self._json(200, run.snapshot(max(0, after)))
            except (KeyError, ValueError) as exc:
                self._json(404, {"error": str(exc)})
            return
        match = re.fullmatch(r"/api/runs/([a-f0-9]+)/file", parsed.path)
        if match:
            self._serve_run_file(match.group(1), parsed.query)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.headers.get("X-Colleague-Token") != self.server.mutation_token:
            self._json(403, {"error": "invalid mutation token"})
            return
        try:
            body = self._body()
            if self.path == "/api/runs":
                run = self.server.registry.create(body)
                self._json(201, run.snapshot())
                return
            match = re.fullmatch(r"/api/runs/([a-f0-9]+)/actions", self.path)
            if match:
                run = self.server.registry.get(match.group(1))
                run.submit(str(body.get("command") or ""))
                self._json(202, {"accepted": True})
                return
            self._json(404, {"error": "not found"})
        except KeyError as exc:
            self._json(404, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def _body(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length") or 0)
        if size > 1_000_000:
            raise ValueError("request body is too large")
        data = json.loads(self.rfile.read(size).decode() or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def _serve_run_file(self, run_id: str, query: str) -> None:
        try:
            run = self.server.registry.get(run_id)
            value = unquote((parse_qs(query).get("path") or [""])[0])
            if value not in run.allowed_files and value != run.result_path:
                raise ValueError("file was not exposed by this run")
            path = Path(value).resolve()
            if not path.is_file():
                raise ValueError("file not found")
            self._bytes(200, path.read_bytes(), mimetypes.guess_type(path.name)[0])
        except (KeyError, OSError, ValueError) as exc:
            self._json(404, {"error": str(exc)})

    def _serve_static(self, raw_path: str) -> None:
        if not WEB_ROOT.exists():
            self._json(
                503,
                {"error": "web build missing; run `cd web && npm run build`"},
            )
            return
        relative = unquote(raw_path).lstrip("/") or "index.html"
        target = (WEB_ROOT / relative).resolve()
        if not target.is_relative_to(WEB_ROOT.resolve()) or not target.is_file():
            target = WEB_ROOT / "index.html"
        self._bytes(200, target.read_bytes(), mimetypes.guess_type(target.name)[0])

    def _json(self, status: int, payload: Any) -> None:
        self._bytes(
            status,
            json.dumps(payload, default=str).encode(),
            "application/json",
        )

    def _bytes(self, status: int, body: bytes, content_type: str | None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="colleague.web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_remote:
        raise SystemExit("refusing a non-loopback bind without --allow-remote")
    server = AppServer((args.host, args.port), Handler)
    host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{host}:{server.server_address[1]}"
    print(f"Colleague human benchmark: {url}")
    print("Runs stay local; press Ctrl-C to stop.")
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
