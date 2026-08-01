"""The unify arm as a conversational session.

unify's runtime is async and its steering lives on a handle, so this adapter
owns an event loop on a background thread and marshals every call onto it.
That keeps the track scenarios synchronous and identical across arms, which
matters more than elegance here: a scenario that reads differently for one
arm is a scenario whose result is about the scenario.

Work is dispatched through `CodeActActor.act`, the same entry point the
`standing` experiments use, rather than through ConversationManager. The
conversation layer would be the more faithful surface for these tracks and
is the obvious v1 upgrade; `act` is what the existing four experiments
already exercise, and reusing it keeps this suite's arms comparable to the
numbers already published.
"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, timezone
from typing import Any

from colleague.arms.sessions import register
from colleague.harness.capability import PROFILES
from colleague.harness.session import ArmSession, Reply, RunHandle, compose

REQUIRED_ENV = ("ORCHESTRA_URL", "UNIFY_KEY")


def require_env() -> None:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"missing required environment: {', '.join(missing)}. "
            "The unify arm runs against staging Orchestra in an isolated context.",
        )


class _LoopThread:
    """An asyncio loop living on its own thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run,
            name="unify-loop",
            daemon=True,
        )
        self._ready = threading.Event()
        self._thread.start()
        self._ready.wait(timeout=10)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        self.loop.run_forever()

    def run(self, coro, timeout: float = 900.0):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


class UnifyRunHandle(RunHandle):
    """One dispatched action, awaited the way its mode requires.

    A non-persistent action ends, and `result()` is the answer. A persistent
    action finishes its turn and then *blocks waiting for the next
    interjection*, so `result()` does not resolve per turn — the turn's answer
    arrives on the notification queue as `{"type": "response", ...}`.

    Awaiting `result()` for a persistent session is what broke the first live
    run of `continuity` and `custody`: the coordinator future resolves once
    and returns the same value on every later await, so a resumed turn
    returned the previous turn's answer instantly and its work was never
    awaited at all. Every continuation scenario reported no side effects.
    """

    def __init__(
        self, loop: _LoopThread, handle: Any, *, persist: bool = False
    ) -> None:
        self._loop = loop
        self._handle = handle
        self._persist = persist
        self._future = None if persist else loop.submit(handle.result())

    def _await_turn(self, timeout: float) -> Reply:
        """Wait for the next surfaced response on a persistent session."""
        deadline = timeout

        async def _next_response() -> str:
            while True:
                note = await self._handle.next_notification()
                if isinstance(note, dict) and note.get("type") == "response":
                    return str(note.get("content") or "")

        try:
            text = self._loop.run(_next_response(), timeout=deadline)
            return Reply(text=text, ok=True, raw=self._handle)
        except TimeoutError:
            return Reply(text="", ok=False, error=f"no response within {deadline}s")
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return Reply(text="", ok=False, error=f"{type(exc).__name__}: {exc}")

    def wait(self, timeout: float = 900.0) -> Reply:
        if self._persist:
            return self._await_turn(timeout)
        try:
            text = self._future.result(timeout=timeout)
            return Reply(text=str(text), ok=True, raw=self._handle)
        except TimeoutError:
            try:
                self._loop.run(self._handle.stop(reason="scenario timeout"), timeout=30)
            except Exception:  # noqa: BLE001 - stop is best-effort on timeout
                pass
            return Reply(text="", ok=False, error=f"timed out after {timeout}s")
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return Reply(text="", ok=False, error=f"{type(exc).__name__}: {exc}")

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        message = text if sender is None else f"[{sender}] {text}"
        self._loop.run(self._handle.interject(message), timeout=120)
        return {"delivered": True, "mode": "live_interject"}

    def ask(self, question: str) -> str:
        return str(self._loop.run(self._handle.ask(question), timeout=180))

    def stop(self) -> None:
        try:
            self._loop.run(self._handle.stop(reason="scenario end"), timeout=60)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass

    @property
    def done(self) -> bool:
        return self._future.done() if self._future is not None else False


class UnifySession(ArmSession):
    profile = PROFILES["unify"]

    def __init__(
        self,
        *,
        run_id: str | None = None,
        track: str = "colleague",
        project: str | None = None,
        ledger: Any = None,
    ) -> None:
        self.run_id = run_id or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%SZ"
        )
        self.track = track
        self.project = project or os.environ.get("COLLEAGUE_PROJECT", "Benchmarks")
        self.ledger = ledger
        self.context = ""
        self._loop: _LoopThread | None = None
        self._actor: Any = None
        self._persistent: UnifyRunHandle | None = None

    def setup(self) -> None:
        require_env()
        self._loop = _LoopThread()

        import unisdk
        import unify as unify_pkg
        from unify.common.context_registry import ContextRegistry
        from unify.manager_registry import ManagerRegistry
        from unify.session_details import (
            UNASSIGNED_ASSISTANT_CONTEXT,
            UNASSIGNED_USER_CONTEXT,
        )

        self.context = (
            f"colleague/{self.track}/{self.run_id}"
            f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
        )
        unisdk.activate(self.project)
        unisdk.create_context(self.context)
        unisdk.set_context(self.context, relative=False)
        ManagerRegistry.clear()
        ContextRegistry.clear()
        unify_pkg.init(project_name=self.project)
        if self.ledger is not None:
            self.ledger.install()

        from unify.actor.code_act_actor import CodeActActor
        from unify.actor.environments import StateManagerEnvironment
        from unify.function_manager.primitives import Primitives

        self.primitives = Primitives()
        self._actor = CodeActActor(
            environments=[StateManagerEnvironment(self.primitives)],
            function_manager=ManagerRegistry.get_function_manager(),
            guidance_manager=ManagerRegistry.get_guidance_manager(),
            knowledge_manager=ManagerRegistry.get_knowledge_manager(),
        )

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
    ) -> RunHandle:
        assert self._loop is not None and self._actor is not None, "call setup() first"
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        handle = self._loop.run(self._actor.act(prompt, persist=persist), timeout=120)
        run = UnifyRunHandle(self._loop, handle, persist=persist)
        if persist:
            self._persistent = run
        return run

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        """Continue the persistent session rather than starting cold.

        There is no separate resume API in unify — continuation is just
        another interjection into a session that finished its work and is
        waiting. The `continuity` track measures what that saves.
        """
        if self._persistent is None:
            raise RuntimeError("no persistent session; call begin(persist=True) first")
        self._persistent.interject(text, sender=sender)
        # The interjection wakes the blocked loop; its answer arrives as the
        # next surfaced response, not by re-awaiting a future that already
        # resolved for the previous turn.
        return self._persistent.wait()

    def close(self) -> None:
        if self._persistent is not None:
            self._persistent.stop()
        if self._loop is not None:
            self._loop.close()

    def artifacts(self) -> dict[str, Any]:
        return {"context": self.context, "project": self.project}


register("unify", UnifySession)
