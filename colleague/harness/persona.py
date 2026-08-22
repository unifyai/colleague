"""The other people in the conversation, played by a model.

A scripted answer to a clarification is not a colleague, it is a stub. When
the assistant asks "which Sarah did you mean?", a real person answers in
their own words, sometimes tersely, sometimes with more than was asked for,
occasionally by questioning the question. An arm that only ever meets
canned replies is being tested against something that does not exist.

So each participant gets a **brief** — who they are, what they know, what
they will and will not say — and answers through a model. The benchmark
supplies people, never APIs-to-people: a persona is owned by the fixture,
persistent for the whole track, listening on every channel the harness's
product exposes, with bounded knowledge, infinite patience, and zero new
information beyond their brief. Arms receive answers only as channel
traffic.

What stays deterministic:

* the **flow** — who speaks, when, and what they say unprompted. Scripted
  turns are still fixed strings fired at fixed waypoints; the scenario's
  request texts are the persona's own authored stimulus, verbatim.
* the **situation** — the fixture data, the seed, the roster.
* the **ground truth** — what a correct answer resolves to, so scoring stays
  exact. The brief carries the facts; the wording is the model's.

What becomes stochastic: anything the assistant *elicits*. Answers to
clarifications, pushback when refused, follow-ups. That is the part worth
making real, and it is the part a fixed script cannot represent. Repeats
(`--repeat`), not single runs, are the unit of measurement for anything a
live persona touches.

Three disciplines make the non-determinism safe to score:

**Labels.** Every reply carries a self-classification the scorers consume
symbolically, so scoring never judges prose. The taxonomy is `LABELS`,
defined here and nowhere else. The label that matters most is
``restated`` — the reply re-supplied information the persona already gave —
because that is the DEGRADED trigger: a correct outcome that consumed a
restated answer is priced, exactly as clarification round-trips always
were, whichever channel carried the exchange.

**The leak guard.** An LLM persona can accidentally reveal what a track
measures (callflow's callee once walked the arm through the branch the
check existed to observe — see SCENARIO_CHANGES.md, "the callee answered
its own question"). Each persona therefore declares ``forbidden`` —
concrete, greppable tokens it must never emit. A reply that carries one is
withheld from delivery, logged in full, and voids the scenario: the runner
resolves it INVALID rather than gifting a PASS or charging a FAIL.

**The implementation switch.** ``COLLEAGUE_PERSONA_IMPL`` selects
``llm`` (default for live runs) or ``scripted`` (today's canned answers,
forced by the runner for the mock arm, which is what the self-test runs) —
so the deterministic validation path never needs a model call.

Persona calls go straight to OpenRouter — never through an arm's recording
proxy — and are metered into their own ledger (``persona_ledger.jsonl`` in
the results dir), reported as ``persona_tokens`` / ``persona_exchanges``
beside arm costs and never added to them. They are the environment, not
the system under test.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from colleague.harness.conversation import Participant
from colleague.harness.fixture_server import utcnow

PERSONA_MODEL = os.environ.get("COLLEAGUE_PERSONA_MODEL", "openai/gpt-5.6-sol")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

#: The reply taxonomy, in one place. Scorers consume these symbolically.
LABELS = (
    "restated",  # re-supplied information the persona already gave
    "repointed",  # directed the arm back without re-supplying content
    "no_information",  # the persona does not know
    "conversational",  # greeting / acknowledgment / thanks; no content
    "silent",  # no reply sent
)

#: Labels that evidence the arm *asked for and received* an informational
#: answer — the set scorers use for "did the arm ask" checks. A repointed or
#: don't-know answer still evidences the ask; a thank-you does not.
INFORMATIONAL_LABELS = ("restated", "repointed", "no_information")


def asks(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The arm's question round-trips this scenario, in order, any channel.

    One entry per persona exchange whose reply was informational — the
    persona restated, repointed, or said they don't know — which is what
    distinguishes "the arm asked someone something" from status traffic a
    person read and let pass. ``who`` is the addressee **as the arm named
    one**: a product channel names its recipient; the clarification hook
    names one only when the arm's own channel did (looked up from the
    session's clarification record); the bare conversation loop names
    nobody, exactly as before — an ask there reaches the requester.
    """
    record = record or {}
    named = {
        str(c.get("question") or "").strip(): str(c.get("who") or "")
        for c in record.get("clarifications") or []
    }
    out: list[dict[str, Any]] = []
    for e in record.get("persona") or []:
        channel = str(e.get("channel") or "")
        if channel == "scene" or e.get("label") not in INFORMATIONAL_LABELS:
            continue
        if channel == "clarification":
            who = named.get(str(e.get("question") or "").strip(), "")
        elif channel == "chat":
            who = ""
        else:
            who = str(e.get("persona") or "")
        out.append(
            {
                "who": who,
                "channel": channel,
                "question": e.get("question"),
                "label": e.get("label"),
            },
        )
    return out


def attended(record: dict[str, Any] | None) -> bool:
    """Whether the arm needed a person this scenario.

    True when it raised a blocking clarification or when any channel
    exchange drew an informational answer. Status updates a persona read
    silently — or acknowledged without content — leave a week unattended:
    reporting to your boss is not needing your boss.
    """
    return bool((record or {}).get("clarifications")) or bool(asks(record))

SYSTEM = """\
You are role-playing one person in a workplace conversation. You are not an \
assistant and you are not being helpful in the abstract — you are this \
person, replying to messages from the AI assistant that works with you, on \
whatever channel they arrive (chat, email, SMS, a question it raised).

{brief}

What you know, and may say if it is relevant to what you were asked:
{knowledge}

Rules:
- Answer as this person would: plainly, briefly, in the first person.
- Never volunteer anything not listed above, and never invent information \
beyond your brief, however many times you are asked. If you are asked \
something you do not know, say you do not know.
- You have infinite patience in substance (repeating yourself is allowed, \
in whatever tone your brief gives you) and zero new information.
- Never do the assistant's work for it: do not supply decisions, judgments \
or moves that are the assistant's to make.
- Do not explain that you are role-playing. Do not add meta-commentary.
- When you do reply: one to three sentences, no greeting, no sign-off.

Respond with ONLY a JSON object, no other text:
  {{"label": "<label>", "reply": "<what you say>"}}

Choose exactly one label:
  "restated"       your reply re-supplies information you already gave \
(in your brief, your own earlier messages, or feedback you sent)
  "repointed"      you direct them back to what you already said WITHOUT \
re-supplying the content itself
  "no_information" you do not know what they are asking about
  "conversational" a greeting, acknowledgment or thanks; no information
  "silent"         no reply is needed (a status update, a confirmation, \
an FYI that a real person would read and not answer) — set "reply" to ""
"""


@dataclass
class PersonaReply:
    """One structured reply: the text, and the label scorers consume."""

    persona: str
    channel: str
    text: str
    label: str
    mode: str
    """model / scripted / fallback / fallback_after_error / label_unparsed."""

    tokens: int = 0
    leaked: list[str] = field(default_factory=list)
    """Forbidden tokens the reply carried. Non-empty means the reply was
    withheld from delivery and the scenario is void (INVALID)."""

    @property
    def deliverable(self) -> bool:
        return self.label != "silent" and not self.leaked and bool(self.text)


@dataclass
class Persona:
    """One participant, plus what they know and how they behave."""

    participant: Participant
    brief: str
    knowledge: dict[str, str] = field(default_factory=dict)
    """Facts this person can disclose, keyed by topic.

    The values carry the ground truth the scenario scores against, so a
    correct answer is stable in substance however it is worded.
    """

    fallback: str = ""
    """Reply used by the scripted implementation — the self-test path.

    Must be a faithful, minimal rendering of `knowledge`, so the mock arm
    exercises the same round trip without spending anything.
    """

    fallback_label: str = "restated"
    """The label the scripted fallback carries. A canned answer that
    re-supplies a known fact is a restatement by construction; a persona
    whose fallback is "I don't know" declares ``no_information``."""

    scripted: Callable[[str, str], tuple[str, str] | None] | None = None
    """Optional scripted responder: ``(message, channel) -> (text, label)``
    or ``None`` to fall through to the default scripted behaviour."""

    forbidden: tuple[str | tuple[str, ...], ...] = ()
    """Leak-guard tokens this persona must never emit — the concrete,
    greppable forms of whatever the track measures. An entry that is itself
    a tuple only counts when all its parts appear together (a fact that is
    only a fact assembled). Checked on every reply in both implementations;
    a hit voids the scenario."""

    channels: tuple[str, ...] = ()
    """Channels this person exists on, informational (the roster/cast is
    authoritative for what the arm can see)."""

    memory: list[dict[str, str]] = field(default_factory=list)
    """Appending transcript of every exchange this persona has had on any
    channel this run: ``{"role": "self"|"assistant", "channel", "text"}``.
    Their own scripted stimulus (the scenario request texts they authored)
    is seeded here too, so "you already said it" is literally true."""

    def _knowledge_block(self) -> str:
        if not self.knowledge:
            return "  (nothing beyond what is in your brief)"
        return "\n".join(f"  - {k}: {v}" for k, v in self.knowledge.items())

    def system_prompt(self) -> str:
        return SYSTEM.format(brief=self.brief, knowledge=self._knowledge_block())

    def remember(self, role: str, channel: str, text: str) -> None:
        self.memory.append({"role": role, "channel": channel, "text": text})


def _parse_labelled(content: str) -> tuple[str, str] | None:
    """``(text, label)`` from the model's JSON, or None if unparsable."""
    blob = content.strip()
    if blob.startswith("```"):
        blob = blob.strip("`")
        if blob.startswith("json"):
            blob = blob[4:]
        blob = blob.strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        # A reply wrapped around the object still counts if the object is
        # findable — models occasionally preface JSON despite instructions.
        start, end = blob.find("{"), blob.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(blob[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    label = str(data.get("label") or "").strip()
    text = str(data.get("reply") or "").strip()
    if label not in LABELS:
        return None
    return text, label


class PersonaPool:
    """Answers as the right person on any channel, and records every exchange.

    One pool per fixture, alive for the whole track. The runner marks
    scenario boundaries (`begin_scenario`) so per-scenario evidence and the
    DEGRADED/INVALID triggers read only that scenario's exchanges, while
    each persona's memory keeps accumulating across the run — a person does
    not forget week 2 when week 3 starts.
    """

    def __init__(self, personas: list[Persona], *, live: bool | None = None) -> None:
        self.personas = {p.participant.id: p for p in personas}
        self._lock = threading.Lock()
        self._log: list[dict[str, Any]] = []
        self._tokens = 0
        self._mark = 0
        self._scenario: str | None = None
        self._overrides: dict[str, dict[str, Any]] = {}
        self._ledger_path: Path | None = None
        self._run_id: str | None = None
        self._forced_scripted = False
        if live is False:
            self._forced_scripted = True

    # ------------------------------------------------------------------ impl

    @property
    def impl(self) -> str:
        """``llm`` or ``scripted`` — which implementation answers.

        Scripted is forced for the mock arm by the runner (which is what the
        self-test runs), so the deterministic validation path never needs a
        model call. Live runs default to ``llm``; without a key the llm path
        degrades per-exchange to the scripted fallback, recorded as such.
        """
        if self._forced_scripted:
            return "scripted"
        return os.environ.get("COLLEAGUE_PERSONA_IMPL", "llm").strip() or "llm"

    def force_scripted(self) -> None:
        self._forced_scripted = True

    @property
    def live(self) -> bool:
        return self.impl == "llm" and bool(os.environ.get("OPENROUTER_API_KEY"))

    # ------------------------------------------------------- scenario window

    def begin_scenario(self, name: str) -> None:
        """Open a scenario window: evidence and triggers read from here."""
        with self._lock:
            self._mark = len(self._log)
            self._scenario = name

    def bind_ledger(self, path: Path, *, run_id: str) -> None:
        self._ledger_path = path
        self._run_id = run_id

    def apply_overrides(self, overrides: dict[str, dict[str, Any]] | None) -> None:
        """Scenario-scoped persona replacements, cleared by the next
        `begin_scenario` caller passing None.

        The reason this exists is control scenarios: `unbriefed_control`
        must meet a Daniel who is information-free about the format — the
        control establishes what the API alone yields, so the persona must
        not be a side door to the spec. An override may replace ``brief``,
        ``knowledge``, ``fallback``, ``fallback_label``, ``forbidden``, and
        set ``fresh_memory`` so the stand-in does not carry the real
        person's transcript either.
        """
        self._overrides = dict(overrides or {})

    def _resolved(self, who: str) -> Persona | None:
        base = self.personas.get(who)
        if base is None:
            return None
        spec = self._overrides.get(who)
        if not spec:
            return base
        return Persona(
            participant=base.participant,
            brief=str(spec.get("brief", base.brief)),
            knowledge=dict(spec.get("knowledge", base.knowledge)),
            fallback=str(spec.get("fallback", base.fallback)),
            fallback_label=str(spec.get("fallback_label", base.fallback_label)),
            scripted=spec.get("scripted", base.scripted),
            forbidden=tuple(spec.get("forbidden", base.forbidden)),
            channels=base.channels,
            memory=[] if spec.get("fresh_memory") else base.memory,
        )

    # -------------------------------------------------------------- stimulus

    def note_authored(self, who: str, text: str, channel: str = "chat") -> None:
        """Seed a line the persona themself authored — a scenario request,
        a scripted turn, a scene beat. This is what lets a persona later
        truthfully restate "what I told you": the brief, the feedback and
        the amendment are in their memory as their own sent messages."""
        persona = self.personas.get(who)
        if persona is not None:
            persona.remember("self", channel, text)

    # ------------------------------------------------------------------- llm

    def _call(self, persona: Persona, message: str, channel: str) -> tuple[str, int]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": persona.system_prompt()},
        ]
        for entry in persona.memory:
            messages.append(
                {
                    "role": "assistant" if entry["role"] == "self" else "user",
                    "content": f"[{entry['channel']}] {entry['text']}",
                },
            )
        messages.append({"role": "user", "content": f"[{channel}] {message}"})
        payload = {
            "model": PERSONA_MODEL,
            "messages": messages,
            "temperature": 1.0,
        }
        req = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode())
        text = body["choices"][0]["message"]["content"].strip()
        used = int((body.get("usage") or {}).get("total_tokens") or 0)
        return text, used

    def _llm_reply(
        self,
        persona: Persona,
        message: str,
        channel: str,
    ) -> tuple[str, str, str, int]:
        """``(text, label, mode, tokens)`` from the model, with one retry
        for an unparsable shape. A still-unparsable reply keeps its raw text
        under the ``restated`` label — the conservative direction: a spec
        re-supply can never slip through unpriced, and the worst case is an
        innocent reply priced DEGRADED, visible in the transcript."""
        content, used = self._call(persona, message, channel)
        parsed = _parse_labelled(content)
        if parsed is None:
            retry, more = self._call(
                persona,
                message
                + '\n\n(Reply with ONLY the JSON object {"label": ..., '
                '"reply": ...} — nothing else.)',
                channel,
            )
            used += more
            parsed = _parse_labelled(retry)
            if parsed is None:
                return content, "restated", "label_unparsed", used
        text, label = parsed
        return text, label, "model", used

    # -------------------------------------------------------------- scripted

    @staticmethod
    def _scripted_reply(persona: Persona, message: str, channel: str) -> tuple[str, str]:
        if persona.scripted is not None:
            result = persona.scripted(message, channel)
            if result is not None:
                return result
        if channel in ("clarification", "reply", "ask"):
            if persona.fallback:
                return persona.fallback, persona.fallback_label
            return "I don't know.", "no_information"
        # Channel traffic (a status update, a filed-report notice) gets no
        # scripted acknowledgment: the deterministic path stays exactly the
        # turn structure the mock plans were written against.
        return "", "silent"

    # ------------------------------------------------------------- the reply

    def reply(
        self,
        who: str,
        message: str,
        *,
        channel: str = "chat",
        expect: tuple[str, ...] = (),
        remember: bool = True,
    ) -> PersonaReply:
        """Answer ``message`` as ``who`` on ``channel``, structured.

        ``expect`` are ground-truth markers a correct reply should carry,
        recorded so the scorer can tell an environment fault from an arm's
        mistake. A persona is a second model, and a second model is a second
        way to fail: if Daniel's stand-in never names Sarah Chen, the arm
        cannot act correctly and would take the blame — an environment fault
        recorded as a statement about the system under test, which is the
        failure mode that has cost this suite the most.

        ``remember`` is off for scene-wording prompts (roleplay's "say this
        beat in your own words"), which are direction, not conversation.
        """
        persona = self._resolved(who)
        if persona is None:
            reply = PersonaReply(
                persona=who,
                channel=channel,
                text="I'm not the right person to ask about that.",
                label="no_information",
                mode="unknown_persona",
            )
            self._record(reply, message, expect=expect)
            return reply

        if self.impl == "scripted" or not self.live:
            text, label = self._scripted_reply(persona, message, channel)
            mode = "scripted" if self.impl == "scripted" else "fallback"
        else:
            try:
                text, label, mode, used = self._llm_reply(persona, message, channel)
            except Exception as exc:  # noqa: BLE001 - recorded; never fails the run
                reply = PersonaReply(
                    persona=who,
                    channel=channel,
                    text=persona.fallback or "I don't know.",
                    label=(
                        persona.fallback_label
                        if persona.fallback
                        else "no_information"
                    ),
                    mode="fallback_after_error",
                )
                self._record(
                    reply,
                    message,
                    expect=expect,
                    error=f"{type(exc).__name__}: {exc}",
                )
                if remember and reply.deliverable:
                    persona.remember("assistant", channel, message)
                    persona.remember("self", channel, reply.text)
                return reply
            reply = PersonaReply(
                persona=who,
                channel=channel,
                text=text,
                label=label,
                mode=mode,
                tokens=used,
            )
            reply.leaked = self._leaks(persona, text, message)
            self._record(reply, message, expect=expect)
            if remember and not reply.leaked:
                persona.remember("assistant", channel, message)
                if reply.label != "silent" and reply.text:
                    persona.remember("self", channel, reply.text)
            return reply

        reply = PersonaReply(
            persona=who,
            channel=channel,
            text=text,
            label=label,
            mode=mode,
        )
        reply.leaked = self._leaks(persona, text, message)
        self._record(reply, message, expect=expect)
        if remember and not reply.leaked:
            persona.remember("assistant", channel, message)
            if reply.label != "silent" and reply.text:
                persona.remember("self", channel, reply.text)
        return reply

    def answer(
        self,
        who: str,
        question: str,
        *,
        channel: str = "clarification",
        expect: tuple[str, ...] = (),
        remember: bool = True,
    ) -> str:
        """Answer as ``who``, plain text — the blocking-hook interface.

        A leak-guarded reply must still return *something* (the arm is
        blocked on it), so a withheld reply degrades to a contentless
        holding line; the scenario is already void by then.
        """
        reply = self.reply(
            who,
            question,
            channel=channel,
            expect=expect,
            remember=remember,
        )
        if reply.leaked:
            return "Let me get back to you on that."
        return reply.text

    # ------------------------------------------------------------ leak guard

    @staticmethod
    def _leaks(persona: Persona, text: str, inbound: str) -> list[str]:
        """Forbidden content the reply *introduces*.

        A token the arm's own message already carried is not a leak — the
        persona revealed nothing by echoing it, and voiding there would
        erase an earned FAIL (an arm that wrongly disclosed a scoped fact
        to the very person who must not have it). What the guard catches is
        the environment supplying the move: content the persona produced
        that the conversation had not given it.

        An entry may be a single token or a tuple of parts that only count
        together — `("thursday", "14:00")` is a fact; "thursday" alone is a
        weekday, and voiding on it would punish ordinary speech.
        """
        blob = (text or "").lower()
        heard = (inbound or "").lower()
        out: list[str] = []
        for entry in persona.forbidden:
            parts = entry if isinstance(entry, tuple) else (entry,)
            if all(
                p.lower() in blob and p.lower() not in heard for p in parts
            ):
                out.append(" + ".join(parts))
        return out

    # --------------------------------------------------------------- records

    def _record(
        self,
        reply: PersonaReply,
        message: str,
        *,
        expect: tuple[str, ...] = (),
        **meta: Any,
    ) -> None:
        blob = reply.text.lower()
        entry: dict[str, Any] = {
            "at": utcnow(),
            "persona": reply.persona,
            "channel": reply.channel,
            "question": message,
            "reply": reply.text,
            "label": reply.label,
            "mode": reply.mode,
            "tokens": reply.tokens,
            **meta,
        }
        if reply.leaked:
            entry["leaked"] = list(reply.leaked)
        if expect:
            entry["expected"] = list(expect)
            entry["delivered"] = all(m.lower() in blob for m in expect)
        with self._lock:
            self._tokens += reply.tokens
            entry["scenario"] = self._scenario
            self._log.append(entry)
        self._ledger_write(entry)

    def _ledger_write(self, entry: dict[str, Any]) -> None:
        if self._ledger_path is None:
            return
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._ledger_path.open("a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "run_id": self._run_id,
                                "model": PERSONA_MODEL if entry["mode"] == "model" else None,
                                **entry,
                            },
                            default=str,
                        )
                        + "\n",
                    )
        except OSError:
            # The in-memory log still carries the exchange; a ledger write
            # failure must never take the run down with it.
            pass

    # ------------------------------------------------------------- consumers

    def transcript(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._log)

    def exchanges(self) -> list[dict[str, Any]]:
        """This scenario's exchanges — the slice scorers read."""
        with self._lock:
            return list(self._log[self._mark :])

    def restated(self) -> list[dict[str, Any]]:
        """This scenario's spec re-supplies — the DEGRADED trigger."""
        return [e for e in self.exchanges() if e.get("label") == "restated"]

    def leaks(self) -> list[dict[str, Any]]:
        """This scenario's leak-guard hits — the INVALID trigger."""
        return [e for e in self.exchanges() if e.get("leaked")]

    def evidence(self) -> dict[str, Any]:
        """This scenario's persona record, for the run file."""
        exchanged = self.exchanges()
        return {
            "persona_exchanges": exchanged,
            "persona_tokens": sum(int(e.get("tokens") or 0) for e in exchanged),
        }

    def delivered(self, *markers: str) -> bool:
        """Whether any reply carried all of ``markers``.

        The scorer's question is not "did every answer contain the fact" —
        a follow-up about something else legitimately will not — but "did
        the environment ever supply what the arm needed". If not, the arm
        was never given what it needed to succeed, and its result is not a
        result.
        """
        wanted = [m.lower() for m in markers]
        with self._lock:
            entries = list(self._log)
        return any(
            all(m in str(e.get("reply", "")).lower() for m in wanted) for e in entries
        )

    @property
    def faulted(self) -> bool:
        """True when a reply was asked to carry ground truth and did not.

        Only meaningful alongside `delivered`: one follow-up missing the
        markers is fine if another exchange supplied them.
        """
        with self._lock:
            entries = [e for e in self._log if "delivered" in e]
        return bool(entries) and not any(e["delivered"] for e in entries)

    @property
    def tokens(self) -> int:
        """Harness spend, reported separately and never charged to the arm."""
        with self._lock:
            return self._tokens
