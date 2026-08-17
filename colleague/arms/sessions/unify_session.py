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
from pathlib import Path
from typing import Any

from colleague.arms.sessions import register
from colleague.harness.capability import PROFILES
from colleague.harness.session import ArmSession, Reply, RunHandle, Unsupported, compose

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
        self,
        loop: _LoopThread,
        handle: Any,
        *,
        persist: bool = False,
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
        results_dir: Any = None,
    ) -> None:
        self.run_id = run_id or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%SZ",
        )
        self.track = track
        self.project = project or os.environ.get("COLLEAGUE_PROJECT", "Benchmarks")
        self.ledger = ledger
        self.results_dir = Path(results_dir) if results_dir else None
        self.context = ""
        self._loop: _LoopThread | None = None
        self._actor: Any = None
        self._persistent: UnifyRunHandle | None = None
        self._responder = None
        self._clarifications: list[dict[str, Any]] = []
        self._turns = 0

    def setup(self) -> None:
        require_env()
        self._loop = _LoopThread()

        import unify as unify_pkg
        import unisdk
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
        # Meter by default. Every CLI arm sits behind the recording proxy;
        # unify has no proxy in front of it, so without this hook its token
        # column is empty while everyone else's is exact — which quietly
        # removes the vendor's own arm from the benchmark's cost axis.
        # Install must come after unify.init, which sets its own global hook.
        if self.ledger is None:
            from colleague.harness.llm_ledger import LLMLedger

            self.ledger = LLMLedger()
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

    def on_clarification(self, responder) -> None:
        self._responder = responder

    def clarifications(self) -> list[dict[str, Any]]:
        return list(self._clarifications)

    def _watch_clarifications(self, handle: Any) -> None:
        """Answer questions the actor raises, through its own channel.

        This is the whole point of the capability: `request_clarification`
        blocks the call site, so the answer resumes the work rather than
        arriving after it. Nothing in the fixture provides this — an arm
        without the channel simply never raises one.
        """

        async def _pump() -> None:
            while True:
                q = await handle.next_clarification()
                question = str(q.get("question") or q.get("content") or "")
                call_id = q.get("call_id") or q.get("id") or ""
                answer = (
                    self._responder(question)
                    if self._responder is not None
                    else "No answer available."
                )
                self._clarifications.append(
                    {"question": question, "answer": answer, "call_id": call_id},
                )
                await handle.answer_clarification(call_id, answer)

        self._loop.submit(_pump())

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        assert self._loop is not None and self._actor is not None, "call setup() first"
        if images:
            # `act` takes image parts, but the conversation layer is where a
            # shared screen arrives in the product; the `unify-cm` arm carries
            # frames through the CM's screenshot buffer. This v0 surface stays
            # text-only rather than inventing a second image path.
            raise Unsupported(
                "the act surface here is text-only; use unify-cm for frames",
            )
        self._turns += 1
        if self.ledger is not None:
            self.ledger.boundary(f"turn_{self._turns}")
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        handle = self._loop.run(self._actor.act(prompt, persist=persist), timeout=120)
        self._watch_clarifications(handle)
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
        self._turns += 1
        if self.ledger is not None:
            self.ledger.boundary(f"turn_{self._turns}")
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
        if self.ledger is not None and self.results_dir is not None:
            try:
                self.results_dir.mkdir(parents=True, exist_ok=True)
                self.ledger.dump(self.results_dir / "unify_ledger.jsonl")
            except Exception:  # noqa: BLE001 - metering must never break a run
                pass

    def artifacts(self) -> dict[str, Any]:
        out: dict[str, Any] = {"context": self.context, "project": self.project}
        if self.ledger is not None:
            try:
                out["llm_segments"] = [s.to_json() for s in self.ledger.segments()]
            except Exception:  # noqa: BLE001 - metering must never break a run
                pass
        return out


register("unify", UnifySession)
