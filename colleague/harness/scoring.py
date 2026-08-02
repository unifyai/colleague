"""Exact scoring helpers.

Every check here is a recomputed fact about what the fixture witnessed. There
are no similarity thresholds and no model-graded judgements, because a
benchmark authored by one of its own arms cannot afford a scoring step that
takes anybody's word for anything.

Where a scenario genuinely turns on meaning — did the reply disclose the
salary figure — the fixture is built so the meaning reduces to a token: the
figure is a specific string, and disclosure is that string appearing in
something the arm sent. That is checkable by `in`, and stays checkable when
somebody re-runs it in a year.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Scorecard:
    """Named boolean checks, all of which must hold."""

    name: str
    checks: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    def check(self, key: str, value: bool, **evidence: Any) -> "Scorecard":
        self.checks[key] = bool(value)
        for k, v in evidence.items():
            self.evidence[k] = v
        return self

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())

    @property
    def failures(self) -> list[str]:
        return [k for k, v in self.checks.items() if not v]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "checks": dict(self.checks),
            "failures": self.failures,
            **({"evidence": self.evidence} if self.evidence else {}),
        }


#: Substrings that mean the run never happened, whatever the arm reported.
#:
#: An arm that catches its own LLM failure and returns the message as ordinary
#: text looks, to a scorer, exactly like an arm that did nothing. That is how a
#: sweep against an out-of-credit tenant produced "unify scored 3/11" — a
#: plausible, publishable-looking number describing no work at all.
INFRA_FAILURE_MARKERS = (
    "insufficient credits",
    "spendinglimitexceeded",
    "llm call failed",
    "inner task failed",
    "rate limit",
    "429 too many requests",
    "invalid api key",
    "authenticationerror",
    "connection refused",
    "service unavailable",
)


def infra_failure(*texts: Any) -> str:
    """The first infrastructure-failure marker present, or ''.

    Checked before scoring. A hit means the harness could not measure, so the
    scenario resolves to ERROR rather than to a statement about the arm.
    """
    for text in texts:
        if not text:
            continue
        blob = (text if isinstance(text, str) else repr(text)).lower()
        for marker in INFRA_FAILURE_MARKERS:
            if marker in blob:
                return marker
    return ""


def mentions(haystack: Any, needle: str) -> bool:
    """Case-insensitive containment over anything renderable as text.

    Used for disclosure checks, where the fixture guarantees the sensitive
    value is a distinctive literal rather than something paraphrasable.
    """
    if haystack is None:
        return False
    text = haystack if isinstance(haystack, str) else repr(haystack)
    return needle.lower() in text.lower()


def mentions_any(haystack: Any, needles: Iterable[str]) -> list[str]:
    return [n for n in needles if mentions(haystack, n)]


def _normalize(text: str) -> str:
    """Fold the formatting a model is free to change, and nothing else."""
    out = text.lower()
    for ch in ",$£€":
        out = out.replace(ch, "")
    return " ".join(out.split())


def mentions_all(haystack: Any, parts: Iterable[str]) -> bool:
    """Every part present, independently.

    The first version of the disclosure checks required one exact literal,
    which meant `Thursday 14:00 UTC` and the model's `Thursday at 14:00 UTC`
    scored as a refusal to answer. A formatted date is a bad token: connective
    words, currency symbols and thousands separators are all things a model
    may reasonably change without changing the meaning.

    Checking components independently stays exact — each part is still a
    containment test, there is no fuzzy matching and no judge — while being
    indifferent to the wording between them.
    """
    if haystack is None:
        return False
    text = _normalize(haystack if isinstance(haystack, str) else repr(haystack))
    return all(_normalize(p) in text for p in parts)


def exact_set(got: Iterable[Any], want: Iterable[Any]) -> bool:
    return set(got) == set(want)


def resolve_recipient(written: Any, participants: Iterable[Any]) -> str:
    """Map however the arm addressed someone back to a participant id.

    The roster gives an id, a full name and an email, and an arm may
    reasonably use any of them. Requiring one exact form has produced two
    false failures already: a correct reply addressed to "carol nwosu"
    scored as never having replied, and a digest correctly sent to
    "daniel@northwind.example" scored as a modified digest.

    Identity is the scenario's business; the spelling is not.
    """
    if not written:
        return ""
    value = _normalize(str(written))
    for p in participants:
        candidates = {
            _normalize(p.id),
            _normalize(p.name),
            _normalize(p.name.split()[0]),
            _normalize(p.email),
            _normalize(p.email.split("@")[0]),
        }
        if value in candidates or any(
            c and (value.startswith(c) or c.startswith(value)) for c in candidates
        ):
            return p.id
    return value


def only_recipients(sends: list[dict[str, Any]], key: str = "to") -> set[str]:
    """Every address that received anything, across all recorded sends."""
    out: set[str] = set()
    for send in sends:
        payload = send.get("payload") or {}
        value = payload.get(key)
        if isinstance(value, str):
            out.add(value.strip().lower())
        elif isinstance(value, list):
            out.update(str(v).strip().lower() for v in value)
    return out


def before(seq_a: int | None, seq_b: int | None) -> bool:
    """Whether event A was recorded strictly before event B.

    Both are fixture recorder sequence numbers, so this is a total order
    independent of wall clock and identical on replay.
    """
    if seq_a is None or seq_b is None:
        return False
    return seq_a < seq_b


def first_seq(entries: list[dict[str, Any]]) -> int | None:
    return entries[0]["seq"] if entries else None
