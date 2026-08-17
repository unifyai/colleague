"""In-process unify runtime for the standing drivers.

Every standing experiment's unify arm boots the same way: staging Orchestra,
an isolated context tree under ``colleague/<experiment>/<run-id>/``, the
CodeAct actor over the state-manager environment, the chained unillm ledger,
and the ConversationManager's due-task delegate mirrored so that
``TaskScheduler.execute`` runs a task exactly as production does. This module
is that boot, written once, so a change to the actor's ``act`` signature is
one edit here rather than one per experiment.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

STAGING_ORCHESTRA_HOST = "api.staging.internal.saas.unify.ai"

#: The one override for running against something other than staging. Named
#: for the first experiment that needed it and kept, so every launcher and
#: every note about it keeps working.
ALLOW_NON_STAGING_ENV = "RWR_ALLOW_NON_STAGING"


def require_env() -> None:
    """Refuse to start unless the launcher prepared the environment."""
    orchestra_url = os.environ.get("ORCHESTRA_URL", "")
    problems = []
    if not orchestra_url:
        problems.append("ORCHESTRA_URL is not set")
    if not os.environ.get("UNIFY_KEY"):
        problems.append("UNIFY_KEY is not set")
    if os.environ.get("UNILLM_CACHE", "").lower() != "false":
        problems.append("UNILLM_CACHE must be 'false'")
    if os.environ.get("TEST", "").lower() != "true":
        problems.append("TEST must be 'true' (benchmark context binding)")
    if os.environ.get("ASSISTANT_ID"):
        problems.append("ASSISTANT_ID must be unset")
    if problems:
        raise SystemExit(
            "Environment not prepared (use the run_unify.sh launcher):\n  - "
            + "\n  - ".join(problems),
        )
    if (
        STAGING_ORCHESTRA_HOST not in orchestra_url
        and os.environ.get(ALLOW_NON_STAGING_ENV) != "true"
    ):
        raise SystemExit(f"ORCHESTRA_URL={orchestra_url} is not staging.")


class BenchmarkTaskExecutionDelegate:
    """Mirror of the ConversationManager due-task delegate.

    Kept in step with
    ``unify.conversation_manager.domains.task_execution``: whatever the
    scheduler passes through ``start_task_run`` reaches ``Actor.act`` with the
    same keywords production uses, and anything unexpected raises rather than
    being dropped on the floor.
    """

    def __init__(self, actor: Any) -> None:
        self._actor = actor

    async def start_task_run(
        self,
        *,
        task_description: str,
        entrypoint: int | None,
        parent_chat_context: list[dict] | None,
        clarification_up_q: asyncio.Queue[str] | None,
        clarification_down_q: asyncio.Queue[str] | None,
        images: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        _ = images
        guidelines = kwargs.pop("guidelines", None)
        entrypoint_kwargs = kwargs.pop("entrypoint_kwargs", None)
        entrypoint_repair_context = kwargs.pop("entrypoint_repair_context", None)
        destination = kwargs.pop("destination", None)
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(
                "BenchmarkTaskExecutionDelegate.start_task_run got unexpected "
                f"keyword arguments: {unexpected}",
            )
        return await self._actor.act(
            task_description,
            guidelines=guidelines,
            entrypoint=entrypoint,
            entrypoint_kwargs=entrypoint_kwargs,
            entrypoint_repair_context=entrypoint_repair_context,
            destination=destination,
            _parent_chat_context=parent_chat_context,
            _clarification_up_q=clarification_up_q,
            _clarification_down_q=clarification_down_q,
            persist=False,
            _reuse_actor_slot=entrypoint is not None,
        )


async def await_handle(handle: Any, timeout_s: float) -> tuple[str, str]:
    """Await a steerable handle's result; returns ``(status, text)``."""
    try:
        text = await asyncio.wait_for(handle.result(), timeout=timeout_s)
        return "completed", str(text)
    except asyncio.TimeoutError:
        try:
            await handle.stop(reason="benchmark phase timeout")
        except Exception as exc:
            return "timeout", f"timed out after {timeout_s}s; stop failed: {exc}"
        return "timeout", f"timed out after {timeout_s}s"
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"


def function_snapshot(function_id: int) -> dict[str, Any]:
    """Name, docstring and source of a stored function, for the run record."""
    from unify.manager_registry import ManagerRegistry

    fm = ManagerRegistry.get_function_manager()
    try:
        log = fm._get_log_by_function_id(function_id=function_id, raise_if_missing=True)
        entries = dict(log.entries)
        return {
            "function_id": function_id,
            "name": entries.get("name"),
            "docstring": entries.get("docstring"),
            "implementation": entries.get("implementation"),
        }
    except Exception as exc:
        return {"function_id": function_id, "error": f"{type(exc).__name__}: {exc}"}


def function_snapshots_by_name() -> dict[str, dict[str, Any]]:
    """Every user-authored stored function, keyed by name.

    A repair rewrites a function in place, so comparing this map before and
    after a fire shows which functions changed — evidence for the run record,
    never a score.
    """
    from unify.manager_registry import ManagerRegistry

    fm = ManagerRegistry.get_function_manager()
    out: dict[str, dict[str, Any]] = {}
    for row in fm._filter_functions_impl(filter=None, limit=500):
        if row.get("is_primitive") or row.get("custom_key"):
            continue
        out[str(row["name"])] = {
            "function_id": row.get("function_id"),
            "implementation": row.get("implementation"),
            "verify": row.get("verify"),
            "side_effect_class": row.get("side_effect_class"),
        }
    return out


@dataclass
class Runtime:
    actor: Any
    scheduler: Any
    ledger: Any
    context: str
    orchestra_url: str


def boot(
    *,
    experiment: str,
    run_id: str,
    project_env: str = "COLLEAGUE_PROJECT",
) -> Runtime:
    """Bring the unify runtime up in an isolated context and return the handles."""
    import unify as unify_pkg
    import unisdk
    from unify.common.context_registry import ContextRegistry
    from unify.manager_registry import ManagerRegistry
    from unify.session_details import (
        UNASSIGNED_ASSISTANT_CONTEXT,
        UNASSIGNED_USER_CONTEXT,
    )

    from colleague.harness.llm_ledger import LLMLedger

    project = os.environ.get(project_env, "Benchmarks")
    ctx = (
        f"colleague/{experiment}/{run_id}"
        f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
    )
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
    print(f"[boot] context={ctx}")
    unisdk.activate(project)
    unisdk.create_context(ctx)
    unisdk.set_context(ctx, relative=False)
    ManagerRegistry.clear()
    ContextRegistry.clear()
    unify_pkg.init(project_name=project)
    ledger = LLMLedger()
    ledger.install()

    from unify.actor.code_act_actor import CodeActActor
    from unify.actor.environments import StateManagerEnvironment
    from unify.function_manager.primitives import Primitives

    primitives = Primitives()
    actor = CodeActActor(
        environments=[StateManagerEnvironment(primitives)],
        function_manager=ManagerRegistry.get_function_manager(),
        guidance_manager=ManagerRegistry.get_guidance_manager(),
        knowledge_manager=ManagerRegistry.get_knowledge_manager(),
    )
    scheduler = ManagerRegistry.get_task_scheduler()
    print("[boot] actor + managers ready")
    return Runtime(
        actor=actor,
        scheduler=scheduler,
        ledger=ledger,
        context=ctx,
        orchestra_url=os.environ["ORCHESTRA_URL"],
    )
