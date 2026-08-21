"""Interactive human participant arm.

The workbench deliberately exposes the same fixture contract the plain-text
arms receive: the request and API documentation are shown verbatim, and the
participant can GET and POST only against that scenario's fixture.  It adds
no answer-bearing convenience API.  Notes, images, named senders, blocking
clarification and live corrections are first-class because those are human
capabilities the benchmark is meant to measure rather than erase.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, TextIO

from colleague.arms.sessions import register
from colleague.harness.capability import ArmProfile, Steering, Storage
from colleague.harness.session import ArmSession, Reply, RunHandle

HUMAN_PROFILE = ArmProfile(
    name="human",
    clarification=True,
    steering=Steering.LIVE_INTERJECT,
    storage=Storage.SCOPED,
    persistent_sessions=True,
    multi_party=True,
    accepts_images=True,
    scheduler=True,
    notes=(
        "A human participant using the benchmark workbench. Persistent notes, "
        "named senders, images, blocking questions and event-relative live "
        "corrections are available. Voice requires the separate room transport."
    ),
)


class HumanRun(RunHandle):
    def __init__(self, session: "HumanSession", fn: Callable[[], Reply]) -> None:
        self.session = session
        self.reply: Reply | None = None
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self.thread.start()

    def _run(self, fn: Callable[[], Reply]) -> None:
        try:
            self.reply = fn()
        except BaseException as exc:  # noqa: BLE001 - returned in the run record
            self.error = exc

    def wait(self, timeout: float = 900.0) -> Reply:
        self.thread.join(timeout)
        if self.thread.is_alive():
            return Reply(text="", ok=False, error=f"timed out after {timeout}s")
        if self.error:
            return Reply(
                text="",
                ok=False,
                error=f"{type(self.error).__name__}: {self.error}",
            )
        return self.reply or Reply(text="", ok=False, error="no reply produced")

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        self.session.deliver_interjection(text, sender=sender)
        return {"delivered": True, "mode": "live_interject"}

    @property
    def done(self) -> bool:
        return not self.thread.is_alive()


class HumanSession(ArmSession):
    """A persistent, metered command-line workbench for one participant."""

    profile = HUMAN_PROFILE

    def __init__(
        self,
        *,
        results_dir: Path | str | None = None,
        hourly_rate_usd: float = 30.0,
        participant_id: str = "anonymous",
        input_fn: Callable[[str], str] = input,
        output: TextIO | None = None,
        **_: Any,
    ) -> None:
        import sys

        self.results_dir = Path(results_dir or ".")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.results_dir / "human_workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.notes_path = self.workspace / "notes.md"
        self.hourly_rate_usd = float(hourly_rate_usd)
        self.participant_id = participant_id
        self.input_fn = input_fn
        self.output = output or sys.stdout
        self.fixture: Any = None
        self.scenario = ""
        self.images: list[str] = []
        self._responder = None
        self._clarifications: list[dict[str, Any]] = []
        self._active_seconds = 0.0
        self._turns = 0
        self._print_lock = threading.Lock()
        self._interjections: list[dict[str, Any]] = []

    def setup(self) -> None:
        self._write(
            "\nHuman workbench ready. Use /help for commands. "
            f"Labour is metered at ${self.hourly_rate_usd:.2f}/hour.",
        )

    def bind_fixture(self, fixture: Any, scenario: str) -> None:
        self.fixture = fixture
        self.scenario = scenario

    def on_clarification(self, responder) -> None:
        self._responder = responder

    def clarifications(self) -> list[dict[str, Any]]:
        return list(self._clarifications)

    def cost_snapshot(self) -> dict[str, Any]:
        return {
            "meter": "human_labor",
            "active_seconds": self._active_seconds,
            "hourly_rate_usd": self.hourly_rate_usd,
            "participant_id": self.participant_id,
            "turns": self._turns,
        }

    def artifacts(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "notes": self.notes_path.read_text() if self.notes_path.exists() else "",
            "interjections": list(self._interjections),
            "cost": self.cost_snapshot(),
        }

    def deliver_interjection(self, text: str, *, sender: str | None = None) -> None:
        entry = {"sender": sender, "text": text, "at": time.time()}
        self._interjections.append(entry)
        self._write(f"\n>>> CORRECTION from {sender or 'participant'}: {text}\n")

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        del persist
        self.images = list(images or [])
        return HumanRun(
            self,
            lambda: self._turn(text=text, context=context, sender=sender),
        )

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        return self._turn(text=text, context=None, sender=sender)

    def _turn(self, *, text: str, context: str | None, sender: str | None) -> Reply:
        started = time.monotonic()
        self._turns += 1
        try:
            self._write("\n" + "=" * 72)
            self._write(f"SCENARIO: {self.scenario or '(continuation)'}")
            if sender:
                self._write(f"FROM: {sender}")
            if context:
                self._write("\nCONTEXT\n" + context)
            self._write("\nREQUEST\n" + text)
            if self.images:
                self._write("\nIMAGES")
                for i, path in enumerate(self.images, 1):
                    self._write(f"  {i}. {path}")
            self._write("\nEnter actions; finish with /done [optional reply text].")
            final = ""
            while True:
                raw = self.input_fn("human> ").strip()
                if not raw:
                    continue
                if raw == "/help":
                    self._help()
                elif raw.startswith("/get "):
                    self._write(self._request("GET", raw[5:].strip(), None))
                elif raw.startswith("/post "):
                    self._post(raw[6:].strip())
                elif raw.startswith("/ask "):
                    self._ask(raw[5:].strip())
                elif raw.startswith("/note "):
                    self._note(raw[6:])
                elif raw == "/notes":
                    self._write(
                        (
                            self.notes_path.read_text()
                            if self.notes_path.exists()
                            else "(none)"
                        ),
                    )
                elif raw == "/images":
                    self._write("\n".join(self.images) or "(none)")
                elif raw.startswith("/open "):
                    self._open_image(raw[6:].strip())
                elif raw.startswith("/shell "):
                    self._shell(raw[7:].strip())
                elif raw.startswith("/done"):
                    final = raw[5:].strip()
                    break
                else:
                    self._write(
                        "Unknown command. Use /help; plain text is never sent implicitly.",
                    )
            return Reply(
                text=final,
                ok=True,
                meta={"participant_id": self.participant_id},
            )
        finally:
            self._active_seconds += time.monotonic() - started

    def _help(self) -> None:
        self._write(
            """Commands:
  /get PATH|URL              GET from this scenario's fixture
  /post PATH JSON            POST a JSON object to the fixture
  /ask WHO QUESTION          ask a named participant and wait for the answer
  /note TEXT                 append a persistent private note
  /notes                     show persistent notes
  /images                    list attached frames
  /open N                    open attached image N with the OS viewer
  /shell COMMAND             run a command in the persistent human workspace
  /done [TEXT]               finish; TEXT becomes the direct reply

Use /post for fixture-observed actions. Nothing is sent by plain text.""",
        )

    def _url(self, value: str) -> str:
        if value.startswith(("http://", "https://")):
            url = value
        elif self.fixture is not None:
            url = f"{self.fixture.base_url}{value if value.startswith('/') else '/' + value}"
        else:
            raise RuntimeError("no fixture is bound")
        if self.fixture is not None:
            target = urllib.parse.urlsplit(url)
            allowed = urllib.parse.urlsplit(self.fixture.base_url)
            if (target.scheme, target.netloc) != (allowed.scheme, allowed.netloc):
                raise ValueError(
                    "the human workbench may access only this scenario's fixture",
                )
        return url

    def _request(self, method: str, target: str, body: Any) -> str:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(target),
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                try:
                    return json.dumps(json.loads(raw or "null"), indent=2)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as exc:
            return f"HTTP {exc.code}: {exc.read().decode()}"

    def _post(self, args: str) -> None:
        try:
            path, body = args.split(maxsplit=1)
            payload = json.loads(body)
        except (ValueError, json.JSONDecodeError) as exc:
            self._write(f"Usage: /post PATH JSON ({exc})")
            return
        self._write(self._request("POST", path, payload))

    def _ask(self, args: str) -> None:
        try:
            who, question = args.split(maxsplit=1)
        except ValueError:
            self._write("Usage: /ask WHO QUESTION")
            return
        answer = self._responder(question, who) if self._responder else "No answer."
        entry = {"who": who, "question": question, "answer": answer}
        self._clarifications.append(entry)
        self._write(f"{who}: {answer}")

    def _note(self, text: str) -> None:
        with self.notes_path.open("a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")
        self._write("Noted.")

    def _open_image(self, value: str) -> None:
        try:
            path = self.images[int(value) - 1]
        except (ValueError, IndexError):
            self._write("Use /open N with an image number from /images.")
            return
        command = ["open", path] if os.name != "nt" else ["cmd", "/c", "start", path]
        try:
            subprocess.Popen(command)  # noqa: S603 - explicit local participant action
            self._write(f"Opened {path}")
        except OSError as exc:
            self._write(f"Could not open image: {exc}")

    def _shell(self, command: str) -> None:
        """Run a participant-authored command in the isolated run workspace."""
        if not command:
            self._write("Usage: /shell COMMAND")
            return
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                shell=True,
                text=True,
                capture_output=True,
                timeout=300,
                check=False,
            )
            output = (completed.stdout + completed.stderr).strip()
            self._write(output or f"exit {completed.returncode}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._write(f"Command failed: {exc}")

    def _write(self, text: str) -> None:
        with self._print_lock:
            print(text, file=self.output, flush=True)


register("human", HumanSession)
