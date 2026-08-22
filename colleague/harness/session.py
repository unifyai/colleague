"""One conversational interface, four harnesses behind it.

The `standing` track wrote a driver per experiment per arm, which was
tolerable at four experiments and would be twenty-four drivers by the end of
this suite. The multi-party tracks share a shape instead: a scenario says
things to an assistant and watches what the fixture records, and the only
thing that varies between arms is what "say something" means.

So an arm implements a session — start it, say something, optionally say
something else while the first thing is still running, close it — and every
track is written once against that interface.

The interesting method is `begin`. It returns before the work is done, which
is what makes mid-task steering measurable at all. `RunHandle.interject`
then does whatever the arm can actually do:

    unify-cm          another inbound event; routing it into the right
                      in-flight action is the measured behaviour
    hermes-tui        session.steer into the running tool batch
    openclaw-gateway  chat.send with queueMode=steer, drained at the next
                      model or tool-launch boundary
    prime-agent-rpc   the steer command's next_turn_boundary lane
    opencode          raises Unsupported — `opencode run` is one-shot,
                      there is no loop to address

Raising is deliberate. A silent no-op would let a scenario record a zero and
imply the arm tried and failed, and that is not what happened.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from colleague.harness.capability import ArmProfile


class Unsupported(RuntimeError):
    """The arm has no mechanism for what was asked.

    Caught by scenarios and turned into `Outcome.UNSUPPORTED`, which is
    reported separately and never averaged into an accuracy figure.
    """


@dataclass
class Reply:
    text: str
    ok: bool = True
    error: str = ""
    raw: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "text": self.text}
        if self.error:
            out["error"] = self.error
        if self.meta:
            out["meta"] = self.meta
        return out


class RunHandle(ABC):
    """Work that has started and has not necessarily finished."""

    @abstractmethod
    def wait(self, timeout: float = 900.0) -> Reply: ...

    @abstractmethod
    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        """Reach the running work. Raises `Unsupported` if the arm cannot."""

    def stop(self) -> None:
        return None

    @property
    def done(self) -> bool:
        return True


class ThreadedRunHandle(RunHandle):
    """Runs a blocking call on a worker thread.

    Every CLI-driven arm looks like this: the command runs to completion and
    there is no way in. Subclasses override `interject` when the arm has one.
    """

    def __init__(self, fn, *args: Any, **kwargs: Any) -> None:
        self._reply: Reply | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            args=(fn, args, kwargs),
            name="arm-run",
            daemon=True,
        )
        self._thread.start()

    def _run(self, fn, args, kwargs) -> None:
        try:
            self._reply = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - surfaced by wait()
            self._error = exc

    def wait(self, timeout: float = 900.0) -> Reply:
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            return Reply(text="", ok=False, error=f"timed out after {timeout}s")
        if self._error is not None:
            return Reply(
                text="",
                ok=False,
                error=f"{type(self._error).__name__}: {self._error}",
            )
        return self._reply or Reply(text="", ok=False, error="no reply produced")

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        raise Unsupported("this arm has no way to address work that is already running")

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()


class ArmSession(ABC):
    """A conversational session with one harness."""

    profile: ArmProfile

    @abstractmethod
    def setup(self) -> None:
        """Bring the harness up. Called once before any turn."""

    @abstractmethod
    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
        attachments: list[str] | None = None,
    ) -> RunHandle:
        """Start a turn and return before it finishes.

        ``context`` is the shared preamble — roster and transcript — that
        every arm receives verbatim, so multi-party scenarios measure what
        the harness does with the information rather than whether it got it.

        ``persist`` asks the arm to keep the session's working state alive
        after the turn completes. Arms without persistent sessions ignore it,
        which is exactly the cost the `continuity` track measures.

        ``images`` are file paths of frames the sender is showing — a shared
        screen — that must reach the arm through whatever visual input path
        it has. An arm with none raises `Unsupported`; a scenario that needs
        them then resolves to UNSUPPORTED rather than to a text-only guess
        scored as a failure to look.

        ``attachments`` are file paths the sender is sharing with the
        message — the documents the work is about. Unlike ``images``, no
        arm may refuse them: a file can always be put where the arm works.
        Each surface takes its own best route — the CM ingests them on its
        product channel, CLI arms find them materialised in the session
        workspace with the message saying where (`attachments.attachment_
        note`, composed once so no arm is told more than another).
        """

    def send(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
        attachments: list[str] | None = None,
        timeout: float = 900.0,
    ) -> Reply:
        return self.begin(
            text,
            persist=persist,
            context=context,
            sender=sender,
            images=images,
            attachments=attachments,
        ).wait(timeout=timeout)

    def close(self) -> None:
        return None

    def artifacts(self) -> dict[str, Any]:
        """Anything the arm produced that belongs in the run record."""
        return {}

    def cost_snapshot(self) -> dict[str, Any]:
        """Cumulative native resource meter, if this arm has one.

        The runner always records wall time. Human sessions additionally
        expose active labour here; metered model adapters expose their native
        token and provider-cost counters.
        """
        return {}

    def on_clarification(self, responder) -> None:
        """Route the arm's native clarification channel to ``responder``.

        ``responder(question, who=None) -> str``. ``who`` is the participant
        the arm addressed, when its channel carries an addressee; the
        responder answers as that person, and as the scenario's default
        persona when the arm's channel has no notion of one. Arms without a
        blocking clarification mechanism ignore this, and scenarios that
        need one resolve to UNSUPPORTED for them rather than scoring them as
        having declined to ask. Whether the arm has the channel is a property
        of the harness and is declared in its profile.
        """
        return None

    def clarifications(self) -> list[dict[str, Any]]:
        """Questions the arm raised through its own channel, with answers.

        Each entry carries ``question`` and ``answer``; arms whose channel
        names an addressee also record ``who``, so a scenario can score
        *whom* the arm asked and not only whether it asked.
        """
        return []


def compose(context: str | None, text: str) -> str:
    """The one place a preamble is glued to a request.

    Kept in one function so no arm can quietly render the shared context
    differently from the others.
    """
    if not context:
        return text
    return f"{context}\n\n---\n\n{text}"
