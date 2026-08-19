"""A scripted arm, for testing the benchmark rather than a harness.

Two uses, both about trusting the suite rather than measuring anything:

**Every scenario must be winnable.** A track supplies an `ideal` plan — the
sequence of API calls a competent assistant would make — and the suite
asserts it scores PASS. A scenario whose ideal plan cannot pass is a broken
scenario, and finding that out costs nothing here and costs real money and a
misleading result if it is discovered from a live run.

**Every scorer must be able to fail.** The same track supplies a `naive`
plan — the plausible wrong thing, the thing a single-loop agent with no
memory of the conversation would do — and the suite asserts it scores FAIL.
A scorer that passes both plans is not measuring anything.

This arm makes no LLM calls and appears in no published result.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, ClassVar

from colleague.arms.sessions import register
from colleague.harness.capability import ArmProfile, Steering, Storage
from colleague.harness.session import ArmSession, Reply, RunHandle, ThreadedRunHandle

MOCK_PROFILE = ArmProfile(
    name="mock",
    clarification=True,
    steering=Steering.LIVE_INTERJECT,
    storage=Storage.SCOPED,
    persistent_sessions=True,
    multi_party=True,
    accepts_images=True,
    scheduler=True,
    notes="Scripted. Used to self-test the suite, never to benchmark anything.",
)


class Client:
    """The tiny HTTP surface a mock plan uses to act on the fixture."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get(self, path: str) -> Any:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=30) as resp:
            return json.loads(resp.read().decode() or "null")

    def post(self, path: str, body: Any) -> Any:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode() or "null")
        except urllib.error.HTTPError as exc:
            return {"error": exc.code}


class MockRun(ThreadedRunHandle):
    def __init__(self, session: "MockSession", fn, *args: Any) -> None:
        self._session = session
        super().__init__(fn, *args)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        self._session.corrections.append({"sender": sender, "text": text})
        return {"delivered": True, "mode": "live_interject"}


class MockSession(ArmSession):
    """Runs a track-supplied plan against the live fixture."""

    profile = MOCK_PROFILE

    #: Durable stores by run id — the mock's stand-in for an arm whose
    #: memory survives its process. The runner's id convention does the
    #: scoping: a track-scoped session and a `restart:` session carry the
    #: run's own id and so read the same store; a `fresh_session:` scenario
    #: carries a suffixed id and gets a blank one, which is exactly the
    #: clean-mind control that key exists for.
    _durable: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(
        self,
        *,
        mode: str = "ideal",
        plan: Callable | None = None,
        run_id: str = "",
        **_: Any,
    ) -> None:
        self.mode = mode
        self._plan = plan
        self.corrections: list[dict[str, Any]] = []
        self._responder = None
        self._clarifications: list[dict[str, Any]] = []
        self.images: list[str] = []
        """Frames handed to the current turn, for plans that 'look'."""
        self.memory: dict[str, Any] = (
            self._durable.setdefault(run_id, {}) if run_id else {}
        )
        """Survives across scenarios, standing in for a live session.

        `ideal` plans read and write it; `naive` plans ignore it, which is
        the cold-restart shape the continuity and custody tracks measure.
        """

        self._fixture: Any = None
        self._scenario: str = ""

    def setup(self) -> None:
        return None

    def on_clarification(self, responder) -> None:
        self._responder = responder

    def clarifications(self) -> list[dict[str, Any]]:
        return list(self._clarifications)

    def ask_user(self, question: str, who: str | None = None) -> str:
        """What a plan calls instead of POSTing a question somewhere.

        ``who`` names the person the plan chose to ask, so a scenario can
        score the choice of addressee and not only the act of asking.
        """
        answer = self._responder(question, who) if self._responder else "No answer."
        entry: dict[str, Any] = {"question": question, "answer": answer}
        if who:
            entry["who"] = who
        self._clarifications.append(entry)
        return answer

    def bind(self, *, fixture: Any, scenario: str, plan: Callable) -> None:
        self._fixture = fixture
        self._scenario = scenario
        self._plan = plan

    def _turn(self, _text: str) -> Reply:
        client = Client(self._fixture.base_url)
        out = self._plan(
            scenario=self._scenario,
            mode=self.mode,
            client=client,
            corrections=self.corrections,
            fixture=self._fixture,
            memory=self.memory,
            ask_user=self.ask_user,
            images=self.images,
        )
        return Reply(text=json.dumps(out, default=str), ok=True)

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        del sender
        return self._turn(text)

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        del persist, context, sender
        self.images = list(images or [])
        return MockRun(self, self._turn, text)


register("mock", MockSession)
