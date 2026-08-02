"""The other people in the conversation, played by a model.

A scripted answer to a clarification is not a colleague, it is a stub. When
the assistant asks "which Sarah did you mean?", a real person answers in
their own words, sometimes tersely, sometimes with more than was asked for,
occasionally by questioning the question. An arm that only ever meets
canned replies is being tested against something that does not exist.

So each participant gets a **brief** — who they are, what they know, what
they will and will not say — and answers through a model.

What stays deterministic:

* the **flow** — who speaks, when, and what they say unprompted. Scripted
  turns are still fixed strings fired at fixed waypoints.
* the **situation** — the fixture data, the seed, the roster.
* the **ground truth** — what a correct answer resolves to, so scoring stays
  exact. The brief carries the facts; the wording is the model's.

What becomes stochastic: anything the assistant *elicits*. Answers to
clarifications, pushback when refused, follow-ups. That is the part worth
making real, and it is the part a fixed script cannot represent.

Persona calls are metered separately and never counted against the arm.
They are the environment, not the system under test.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from colleague.harness.conversation import Participant
from colleague.harness.fixture_server import utcnow

PERSONA_MODEL = os.environ.get("COLLEAGUE_PERSONA_MODEL", "openai/gpt-5.6-sol")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = """\
You are role-playing one person in a workplace conversation. You are not an \
assistant and you are not being helpful in the abstract — you are this \
person, replying to a message from the AI assistant that works with you.

{brief}

What you know, and may say if it is relevant to what you were asked:
{knowledge}

Rules:
- Answer as this person would: plainly, briefly, in the first person.
- Never volunteer anything not listed above. If you are asked something you \
do not know, say you do not know.
- Do not explain that you are role-playing. Do not add meta-commentary.
- One to three sentences. No greeting, no sign-off.
"""


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
    """Reply used when no model is available — the self-test path.

    Must be a faithful, minimal rendering of `knowledge`, so the mock arm
    exercises the same round trip without spending anything.
    """

    def _knowledge_block(self) -> str:
        if not self.knowledge:
            return "  (nothing beyond what is in your brief)"
        return "\n".join(f"  - {k}: {v}" for k, v in self.knowledge.items())

    def system_prompt(self) -> str:
        return SYSTEM.format(brief=self.brief, knowledge=self._knowledge_block())


class PersonaPool:
    """Answers questions as the right person, and records every exchange."""

    def __init__(self, personas: list[Persona], *, live: bool | None = None) -> None:
        self.personas = {p.participant.id: p for p in personas}
        self._lock = threading.Lock()
        self._log: list[dict[str, Any]] = []
        self._tokens = 0
        # Live by default when a key exists; the self-test runs without one
        # and gets the fallback, so it stays free and deterministic.
        self.live = (
            live if live is not None else bool(os.environ.get("OPENROUTER_API_KEY"))
        )

    def _call(self, persona: Persona, question: str) -> tuple[str, int]:
        payload = {
            "model": PERSONA_MODEL,
            "messages": [
                {"role": "system", "content": persona.system_prompt()},
                {"role": "user", "content": question},
            ],
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

    def answer(self, who: str, question: str) -> str:
        persona = self.personas.get(who)
        if persona is None:
            return "I'm not the right person to ask about that."

        if not self.live:
            reply = persona.fallback or "I don't know."
            self._record(who, question, reply, tokens=0, mode="fallback")
            return reply

        try:
            reply, used = self._call(persona, question)
            self._record(who, question, reply, tokens=used, mode="model")
            return reply
        except (
            Exception
        ) as exc:  # noqa: BLE001 - recorded; falls back rather than failing the run
            reply = persona.fallback or "I don't know."
            self._record(
                who,
                question,
                reply,
                tokens=0,
                mode="fallback_after_error",
                error=f"{type(exc).__name__}: {exc}",
            )
            return reply

    def _record(self, who: str, question: str, reply: str, **meta: Any) -> None:
        with self._lock:
            self._tokens += int(meta.get("tokens") or 0)
            self._log.append(
                {
                    "at": utcnow(),
                    "persona": who,
                    "question": question,
                    "reply": reply,
                    **meta,
                },
            )

    def transcript(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._log)

    @property
    def tokens(self) -> int:
        """Harness spend, reported separately and never charged to the arm."""
        with self._lock:
            return self._tokens
