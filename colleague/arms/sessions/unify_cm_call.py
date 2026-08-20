"""The unify-cm arm's dial surface: its real make_call path, end to end.

The product's outbound call is a chain the benchmark wants whole: the slow
brain's `make_call(contact_id, opener, briefing, allow_hang_up)` queues the
verbatim opener and the unspoken briefing, `comms_utils.start_call` POSTs the
dial to the telephony gateway, the `PhoneCallSent` event dispatches the fast
brain (`medium_scripts/call.py`) into the LiveKit room, and the call script
asks the comms service to create its LiveKit agent dispatch. This bridge
drives all of it against the harness's exchange instead of the hosted
gateway, changing where the provider *is*, never what the arm *does*:

- The arm boots with `apply_test_mocks=True` (the CM test recipe), which
  stubs exactly two things on this path: the module-level
  `comms_utils.start_call` and the instance's `call_manager.start_call`.
  Both are restored for the duration of the call surface — the module
  function by re-executing `comms_utils` in a scratch module and taking the
  product's own function from it (nothing is reimplemented), the instance
  method by removing the stub so lookup falls through to the class, the same
  move the meet bridge makes by calling through the class. Every other comms
  mock stays in place, and both stubs are put back on detach.

- `UNIFY_COMMS_URL` points at the exchange: in `os.environ` for the worker
  subprocess (which reads settings fresh at boot), and on the live
  `SETTINGS.conversation.COMMS_URL` for the in-process dial (settings were
  instantiated before the exchange's port existed).

- `_outbound_ready_override` stays set: this boot has no prewarmed worker
  pool, and the per-call subprocess is the CM's own production fallback for
  exactly that state — the same path the meet bridge exercises.

- The assistant's utterance text is taken from the arm itself:
  `OutboundPhoneUtterance` on `app:comms:phone_call_utterance` carries the
  exact string the fast brain handed its TTS, and the bridge passes it to
  the callee's capture — scoring reads the arm's own words, never a
  transcription of them.

- A provider status callback flows the other way: when the harness's line
  rings out, `deliver_status("no-answer")` publishes `PhoneCallNotAnswered`
  onto the CM's broker — the event the hosted telephony webhook would have
  produced — and the CM's own handler cleans up the agent and wakes the
  brain to deal with it.

Same metering caveat as the meet bridge, stated: the fast brain runs in the
worker subprocess, whose LLM calls do not pass through the in-process
ledger. Slow-brain calls remain metered; the worker's own logs are the
evidence for fast-brain spend.

This module is the delimited dial extension of `unify_cm_session.py`; the
session file itself carries only the two-line delegation, because another
stream owns its text-side behaviour.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from typing import Any, Callable

from colleague.arms.sessions.unify_cm_voice import prime_voice_env

_UTTERANCE_CHANNEL = "app:comms:phone_call_utterance"
#: The channel carries both directions of the call — the arm's own lines and
#: what its STT heard the callee say — so the tap must take only the
#: outbound event, or the callee's words get scored as the arm's.
_OUTBOUND_UTTERANCE = "OutboundPhoneUtterance"


def outbound_utterance_content(message: str, event_name: str) -> str:
    """The spoken text of one outbound utterance event, or "".

    Events serialize nested — ``{"event_name": ..., "payload": {...,
    "content": ...}}`` — and a flat ``.get("content")`` reads None forever
    (found live: a whole call scored on transcription while the arm's exact
    text sailed past the tap). Parsed defensively so a flat legacy payload
    still reads.
    """
    try:
        data = json.loads(message)
    except Exception:  # noqa: BLE001 - non-JSON payloads pass through
        return ""
    if not isinstance(data, dict):
        return ""
    name = str(data.get("event_name") or "")
    if name and name != event_name:
        return ""
    payload = data.get("payload")
    if not isinstance(payload, dict):
        payload = data
    return str(payload.get("content") or "")


def _pristine_comms_start_call() -> Any:
    """The product's own `start_call`, recovered from a scratch execution.

    `_apply_test_mocks` rebinds the module attribute and keeps no reference
    to the original, so the function is re-obtained by executing the module's
    source once more under a scratch name. Its top level is imports plus two
    None globals and an idempotent `load_dotenv()`; every singleton it
    touches (SETTINGS, SESSION_DETAILS) resolves through `sys.modules` to the
    live objects, so the recovered function behaves exactly as the shipped
    one — it *is* the shipped one.
    """
    from unify.conversation_manager.domains import comms_utils

    spec = comms_utils.__spec__
    scratch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scratch)
    return scratch.start_call


class UnifyCMCallBridge:
    """One armed dial surface per bridge; built by `attach_call_surface`."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._on_text: Callable[[str], None] | None = None
        self._orig_publish: Any = None
        self._mock_start_call: Any = None
        self._mock_manager_start_call: Any = None
        self._prev_comms_url: str | None = None
        self._prev_comms_env: str | None = None
        self._callee_contact: dict[str, Any] | None = None
        self._attached = False

    # ---------------------------------------------------------------- attach

    def attach(self, invite: Any, *, on_text: Callable[[str], None]) -> dict[str, Any]:
        session = self._session
        assert session._loop is not None and session._cm is not None
        self._on_text = on_text

        prime_voice_env(invite.livekit_url)
        self._prime_comms(invite.comms_url)
        self._restore_outbound()
        self._tap_utterances()
        session._loop.run(self._give_number(invite), timeout=60)
        self._attached = True
        return {"deliver_status": self.deliver_status}

    def _prime_comms(self, comms_url: str) -> None:
        """Point both readers of the comms URL at the exchange.

        The worker subprocess builds settings from the environment it
        inherits; the in-process CM built its settings before the exchange
        existed, so the live object is updated too. Both are restored on
        detach.
        """
        self._prev_comms_env = os.environ.get("UNIFY_COMMS_URL")
        os.environ["UNIFY_COMMS_URL"] = comms_url
        from unify.settings import SETTINGS

        self._prev_comms_url = SETTINGS.conversation.COMMS_URL
        SETTINGS.conversation.COMMS_URL = comms_url

    def _restore_outbound(self) -> None:
        from unify.conversation_manager.domains import comms_utils

        self._mock_start_call = comms_utils.start_call
        comms_utils.start_call = _pristine_comms_start_call()

        manager = self._session._cm.call_manager
        # The instance stub shadows the class method; removing it restores
        # the real one without touching the class or the other mocks.
        self._mock_manager_start_call = manager.__dict__.pop("start_call", None)

    def _tap_utterances(self) -> None:
        """Compose over the session's broker tap to hand utterance text out.

        The worker's events reach the CM broker through the IPC socket
        server's republish, so wrapping `event_broker.publish` sees every
        spoken line exactly once — the same seam the meet bridge uses, one
        channel over.
        """
        cm = self._session._cm
        self._orig_publish = cm.event_broker.publish
        orig = self._orig_publish
        on_text = self._on_text

        async def tapping_publish(channel: str, message: str) -> int:
            if channel == _UTTERANCE_CHANNEL and on_text is not None:
                content = outbound_utterance_content(message, _OUTBOUND_UTTERANCE)
                if content.strip():
                    on_text(content)
            return await orig(channel, message)

        cm.event_broker.publish = tapping_publish

    async def _give_number(self, invite: Any) -> None:
        """Put the callee's number on their contact row.

        The number is the world, not a hint: an assistant asked to call the
        clinic would have the clinic's number on file (and the call brief
        carries it in prose for arms without a contact store). `make_call`
        requires it there or passed inline; seeding the row is the
        store-backed arm's version of the same fact every arm gets.
        """
        key = (getattr(invite, "callee_id", "") or "").strip().lower()
        contact = self._session._correspondents.get(key)
        if not contact or contact.get("contact_id") is None:
            return
        cm = self._session._cm
        # The store validates numbers as E.164-compact (`^\+?[0-9]+$`); the
        # invite carries the human-formatted number the tree states. Same
        # number, the store's spelling — the exchange matches dials by
        # digits, so either rendering rings the same line.
        cm.contact_manager.update_contact(
            contact_id=int(contact["contact_id"]),
            phone_number=re.sub(r"[^\d+]", "", invite.number),
        )
        refreshed = self._session._contact_dict(int(contact["contact_id"]))
        self._session._correspondents[key] = refreshed
        self._callee_contact = refreshed

    # ---------------------------------------------------------------- status

    def deliver_status(self, status: str) -> None:
        """A provider status callback, delivered as the webhook would be.

        "answered" becomes `PhoneCallAnswered` — the CM forwards it to the
        voice agent as `call_answered`, which is the gate an outbound
        opener waits behind (call.py holds its opening turn until the
        provider says the callee picked up; the first live run proved a
        silent provider means a silent agent). Anything else is a
        not-answered disposition (`PhoneCallNotAnswered`): the CM's own
        handler stops the agent, cleans up, and wakes the brain. Both are
        the exact events the hosted telephony path publishes.
        """
        session = self._session
        if session._loop is None or session._cm is None:
            return
        ev = session._M.ev
        contact = self._callee_contact or {}
        if status == "answered":
            event = ev.PhoneCallAnswered(contact=contact)
        else:
            event = ev.PhoneCallNotAnswered(
                contact=contact,
                reason=status or "no-answer",
            )
        session._loop.run(self._publish_between_steps(event), timeout=200)

    async def _publish_between_steps(self, event: Any) -> None:
        """Publish a provider event once no stepped turn is in flight.

        The session's stepped driver swaps the broker's publish for a wrapper
        that handles Events inline and *drops* non-Event payloads — and the
        `call_answered` status the CM forwards to its voice agent is exactly
        such a payload. A webhook landing mid-step would therefore run its
        handler whole and still lose the one message the handler exists to
        send. Between steps the untouched pipeline (tap → recorder → real
        broker → the CM's background loop → the IPC socket, which buffers for
        a client that has not connected yet) carries it exactly as production
        does, so the delivery waits for that moment.
        """
        import asyncio

        session = self._session
        for _ in range(900):  # up to ~3 minutes
            if not session._processing and session._queue.empty():
                break
            await asyncio.sleep(0.2)
        await session._cm.event_broker.publish(event.topic, event.to_json())

    # ---------------------------------------------------------------- detach

    def detach(self) -> None:
        session = self._session
        if session._loop is None or session._cm is None:
            return
        try:
            session._loop.run(self._end(), timeout=60)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        cm = session._cm
        if self._orig_publish is not None:
            cm.event_broker.publish = self._orig_publish
            self._orig_publish = None
        if self._mock_start_call is not None:
            from unify.conversation_manager.domains import comms_utils

            comms_utils.start_call = self._mock_start_call
            self._mock_start_call = None
        if self._mock_manager_start_call is not None:
            cm.call_manager.start_call = self._mock_manager_start_call
            self._mock_manager_start_call = None
        if self._prev_comms_url is not None:
            from unify.settings import SETTINGS

            SETTINGS.conversation.COMMS_URL = self._prev_comms_url
            self._prev_comms_url = None
        if self._prev_comms_env is None:
            os.environ.pop("UNIFY_COMMS_URL", None)
        else:
            os.environ["UNIFY_COMMS_URL"] = self._prev_comms_env
            self._prev_comms_env = None
        self._attached = False

    async def _end(self) -> None:
        cm = self._session._cm
        try:
            await cm.call_manager.end_call("scenario end")
        except Exception:  # noqa: BLE001
            pass
        import asyncio

        await asyncio.sleep(1.0)
        try:
            await cm.call_manager.cleanup_call_proc()
        except Exception:  # noqa: BLE001
            pass
