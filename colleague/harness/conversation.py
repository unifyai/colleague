"""Multi-party conversation, rendered identically for every arm.

The point of these tracks is to measure what a harness does with several
people talking to it. That only measures the harness if every arm receives
the same information about who is speaking — otherwise the result is just
"unify has a contact model and the others were not told who anyone is",
which is a fact about the fixture, not about the architecture.

So the transcript renders to labelled plain text and the roster renders to a
plain table, and both go to every arm verbatim. An arm with no notion of
participants can still read `[Bob Ferrall — contractor]` and act correctly.
Whether it does is the measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Participant:
    id: str
    name: str
    role: str
    email: str
    standing: str = ""
    """What this person is entitled to, in plain language.

    Rendered into the roster every arm sees. Deliberately explicit: the
    scenarios test whether a harness *acts* on standing it has been told,
    not whether it can infer standing it was never given.
    """

    teams: tuple[str, ...] = ()
    """Teams this person belongs to, by name.

    Membership is structure, not policy: it says where a person can read
    from, and a fact said inside a team is thereby scoped to that team.
    Rendered into the roster like everything else, so a text-only arm has
    the same information as one with a real team model — the measurement is
    whether the arm acts on it.
    """

    def label(self) -> str:
        return f"{self.name} — {self.role}"


@dataclass
class Message:
    sender: str
    text: str
    note: str = ""
    """Harness-side annotation, never rendered to the arm."""


@dataclass
class Transcript:
    participants: list[Participant]
    messages: list[Message] = field(default_factory=list)

    def by_id(self, pid: str) -> Participant:
        for p in self.participants:
            if p.id == pid:
                return p
        raise KeyError(f"no participant {pid!r}")

    def say(self, sender: str, text: str, note: str = "") -> "Transcript":
        self.by_id(sender)
        self.messages.append(Message(sender=sender, text=text, note=note))
        return self

    def roster(self) -> str:
        lines = ["People in this workspace:"]
        for p in self.participants:
            entry = f"- {p.name} ({p.role}), {p.email}"
            if p.teams:
                entry += f". Member of: {', '.join(p.teams)}"
            if p.standing:
                entry += f". {p.standing}"
            lines.append(entry)
        return "\n".join(lines)

    def render(self, upto: int | None = None) -> str:
        """The conversation so far, with every turn attributed."""
        msgs = self.messages if upto is None else self.messages[:upto]
        lines = []
        for m in msgs:
            lines.append(f"[{self.by_id(m.sender).label()}] {m.text}")
        return "\n".join(lines)

    def preamble(self, upto: int | None = None) -> str:
        """Roster plus transcript: the shared context block every arm gets."""
        return f"{self.roster()}\n\nConversation so far:\n\n{self.render(upto)}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "participants": [
                {
                    "id": p.id,
                    "name": p.name,
                    "role": p.role,
                    "email": p.email,
                    "standing": p.standing,
                    "teams": list(p.teams),
                }
                for p in self.participants
            ],
            "messages": [
                {
                    "sender": m.sender,
                    "text": m.text,
                    **({"note": m.note} if m.note else {}),
                }
                for m in self.messages
            ],
        }
