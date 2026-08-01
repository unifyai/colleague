"""Shared-policy fixture for the policy propagation benchmark.

One seeded inquiry stream (an extension of semantic_triage's generator with
urgency-relevant content), consumed by THREE independent automations that
each maintain their own cursor against their own sink:

    triage  — per-inquiry category + priority        (POST /triage)
    digest  — urgent counts per category             (POST /digests)
    audit   — urgent totals and fraction             (POST /audits)

All three apply the same **escalation policy**: an inquiry is urgent when it
mentions a dollar amount of >= THRESHOLD, or when the customer says they are
blocked from working. The harness changes the threshold mid-series (a single
natural-language policy-update message to the system under test); golden
labels are computed against the policy epoch in force at fire time, so a
stale copy of the policy in any automation shows up as wrong priorities —
a reliability number, not an aesthetic complaint.

Golden urgency is certain by construction: each template either carries a
dollar-amount slot (urgent iff amount >= threshold), is a "blocked from
working" template (always urgent), or is neither (never urgent).

Endpoints:
    GET  /health
    GET  /inquiries?after=N            -> up to 200 inquiries {seq, text}
    GET  /{sink}/last                  -> {"last_seq": N}   (sink in triage|digests|audits)
    POST /{sink}                       -> stores the JSON body
    GET  /{sink}                       -> all stored bodies (with receipt metadata)
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

CATEGORIES = ("refund", "bug", "sales", "other")
SINKS = ("triage", "digests", "audits")
PAGE_LIMIT = 200

DEFAULT_SEED = 20260731
DEFAULT_PORT = 8132

INITIAL_THRESHOLD = 500
UPDATED_THRESHOLD = 250

# Weighted so threshold-sensitive values ($250 <= x < $500 flips with the
# policy change; $650/$999 stay urgent) appear in every scoring window.
_AMOUNT_VALUES = (310, 650, 310, 999, 310, 650, 310, 19, 310, 120)
_PRODUCTS = (
    "the analytics dashboard",
    "the mobile app",
    "the API",
    "the browser extension",
    "the desktop client",
)
_COUNTS = ("15", "40", "80", "200", "500")

# kind: "amount" templates carry {amount} and are urgent iff value >= threshold;
# "blocked" templates state the customer cannot work and are always urgent;
# "plain" templates are never urgent.
_TEMPLATES: dict[str, tuple[tuple[str, str], ...]] = {
    "refund": (
        (
            "amount",
            "I was charged {amount} twice for {product} and want the second charge reversed.",
        ),
        (
            "amount",
            "My card was billed {amount} after I cancelled — please send my money back.",
        ),
        (
            "amount",
            "Please reverse yesterday's charge of {amount}; I did not authorize it.",
        ),
        (
            "amount",
            "You billed me {amount} for a plan I downgraded out of. Credit it back to my card.",
        ),
        (
            "plain",
            "I bought the annual plan by mistake instead of monthly — please undo that charge.",
        ),
        (
            "plain",
            "Cancelled during the trial but still got charged — I'd like that back on my card.",
        ),
        (
            "blocked",
            "Your duplicate charge overdrew our account and we are blocked from working until it is repaid.",
        ),
    ),
    "bug": (
        ("plain", "The export button downloads an empty file every time I click it."),
        ("plain", "Two-factor codes are rejected even when typed correctly."),
        ("plain", "{product} shows a blank page right after login since this morning."),
        ("plain", "Exporting my invoice history to CSV produces a corrupted file."),
        ("plain", "Push notifications from {product} arrive three hours late."),
        (
            "blocked",
            "The editor crashes on open, so I am completely blocked from working until this is fixed.",
        ),
        (
            "blocked",
            "Login loops forever on our whole team's accounts — nobody can do any work today.",
        ),
    ),
    "sales": (
        (
            "plain",
            "We're budgeting for the enterprise tier next quarter — can someone send a quote?",
        ),
        (
            "plain",
            "Is the annual plan still available at last year's rate if we sign this week?",
        ),
        ("plain", "Can we schedule a demo of {product} for our procurement committee?"),
        (
            "plain",
            "We're comparing vendors this quarter — can someone walk us through pricing tiers?",
        ),
        ("plain", "Do you offer discounts if we purchase {count} seats for our team?"),
        ("plain", "My boss asked me to get a quote for company-wide adoption."),
        (
            "plain",
            "Our contract is up for renewal and we want to talk about expanding usage.",
        ),
    ),
    "other": (
        (
            "plain",
            "Where do I update our company's billing address for future invoices?",
        ),
        ("plain", "Where can I download my invoice history for our accountant?"),
        ("plain", "How do I change which email address gets billing receipts?"),
        (
            "plain",
            "Is there a status page I can watch during your maintenance windows?",
        ),
        ("plain", "How do I add a teammate as an admin on our workspace?"),
        ("plain", "How do I turn off the weekly digest emails?"),
        (
            "blocked",
            "I forgot my admin password and I'm blocked from working until someone resets it — who do I contact?",
        ),
    ),
}

POLICY_STATEMENT = (
    "Our escalation policy: an inquiry is urgent when it involves a charge, "
    "billing amount, or refund of $500 or more, or when the customer says "
    "they are blocked from working. All other inquiries are normal."
)

POLICY_UPDATE_MESSAGE = (
    "We've updated our escalation policy: the billing-amount threshold for "
    "urgent is now $250 or more (the blocked-from-working rule is "
    "unchanged). Please "
    "make sure every automation we have applies the updated policy from now "
    "on. Do not ask for confirmation."
)


def _h(seed: int, *parts: Any) -> int:
    payload = ":".join([str(seed), *map(str, parts)]).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def inquiry_for_seq(seed: int, seq: int) -> dict[str, Any]:
    """The unique inquiry at ``seq``: text plus golden category/kind/amount."""
    h = _h(seed, "pp-inquiry", seq)
    category = CATEGORIES[h % len(CATEGORIES)]
    kind, template = _TEMPLATES[category][(h >> 8) % len(_TEMPLATES[category])]
    amount_value = _AMOUNT_VALUES[(h >> 16) % len(_AMOUNT_VALUES)]
    text = template.format(
        amount=f"${amount_value}",
        product=_PRODUCTS[(h >> 24) % len(_PRODUCTS)],
        count=_COUNTS[(h >> 32) % len(_COUNTS)],
    )
    return {
        "seq": seq,
        "text": text,
        "category": category,
        "kind": kind,
        "amount_value": amount_value if kind == "amount" else None,
    }


def golden_priority(seed: int, seq: int, threshold: int) -> str:
    row = inquiry_for_seq(seed, seq)
    if row["kind"] == "blocked":
        return "urgent"
    if row["kind"] == "amount" and int(row["amount_value"]) >= threshold:
        return "urgent"
    return "normal"


def expected_triage(seed: int, start: int, end: int, threshold: int) -> dict[str, Any]:
    return {
        "batch_start_seq": start,
        "batch_end_seq": end,
        "classifications": [
            {
                "seq": s,
                "category": inquiry_for_seq(seed, s)["category"],
                "priority": golden_priority(seed, s, threshold),
            }
            for s in range(start, end + 1)
        ],
    }


def expected_digest(seed: int, start: int, end: int, threshold: int) -> dict[str, Any]:
    by_cat = {c: 0 for c in CATEGORIES}
    for s in range(start, end + 1):
        if golden_priority(seed, s, threshold) == "urgent":
            by_cat[inquiry_for_seq(seed, s)["category"]] += 1
    return {
        "batch_start_seq": start,
        "batch_end_seq": end,
        "urgent_by_category": by_cat,
        "urgent_total": sum(by_cat.values()),
    }


def expected_audit(seed: int, start: int, end: int, threshold: int) -> dict[str, Any]:
    total = end - start + 1
    urgent = sum(
        1
        for s in range(start, end + 1)
        if golden_priority(seed, s, threshold) == "urgent"
    )
    return {
        "batch_start_seq": start,
        "batch_end_seq": end,
        "urgent_count": urgent,
        "total_count": total,
        "urgent_fraction": round(urgent / total, 2) if total else 0.0,
    }


def score_sink_batch(
    sink: str,
    actual: Any,
    *,
    seed: int,
    start: int,
    end: int,
    threshold: int,
) -> dict[str, Any]:
    """Exact-match scoring for one delivered batch on one sink.

    For triage, ``accuracy`` grades per-item (category, priority) pairs so a
    stale-policy automation degrades measurably instead of binarily; for the
    aggregate sinks the payload is exact-match and accuracy is 1.0/0.0.
    """
    builders = {
        "triage": expected_triage,
        "digests": expected_digest,
        "audits": expected_audit,
    }
    expected = builders[sink](seed, start, end, threshold)
    if not isinstance(actual, dict):
        return {"contract_correct": False, "accuracy": 0.0, "expected": expected}

    if sink == "triage":
        checks = {
            "batch_start_seq": actual.get("batch_start_seq") == start,
            "batch_end_seq": actual.get("batch_end_seq") == end,
            "no_extra_keys": not (
                set(actual) - {"batch_start_seq", "batch_end_seq", "classifications"}
            ),
        }
        raw = actual.get("classifications")
        per_item: dict[int, tuple[Any, Any]] = {}
        well_formed = isinstance(raw, list)
        if well_formed:
            for entry in raw:
                if not isinstance(entry, dict) or not isinstance(entry.get("seq"), int):
                    well_formed = False
                    break
                per_item[entry["seq"]] = (entry.get("category"), entry.get("priority"))
        checks["classifications_well_formed"] = well_formed
        checks["covers_all_seqs_exactly_once"] = well_formed and set(per_item) == set(
            range(start, end + 1),
        )
        graded = [
            (
                per_item.get(s),
                (
                    inquiry_for_seq(seed, s)["category"],
                    golden_priority(seed, s, threshold),
                ),
            )
            for s in range(start, end + 1)
        ]
        correct = sum(1 for got, want in graded if got == want)
        priority_correct = sum(
            1 for got, want in graded if got is not None and got[1] == want[1]
        )
        total = len(graded)
        return {
            "contract_correct": all(checks.values()),
            "accuracy": round(correct / total, 4) if total else 0.0,
            "priority_accuracy": round(priority_correct / total, 4) if total else 0.0,
            "checks": checks,
            "expected": expected,
        }

    exact = actual == expected
    return {
        "contract_correct": exact,
        "accuracy": 1.0 if exact else 0.0,
        "expected": expected,
    }


@dataclass
class PolicyStream:
    seed: int = DEFAULT_SEED
    released_seq: int = 0
    sinks: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {s: [] for s in SINKS},
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def release(self, count: int) -> int:
        with self._lock:
            self.released_seq += count
            return self.released_seq

    def inquiries_after(self, after: int) -> list[dict[str, Any]]:
        with self._lock:
            released = self.released_seq
        start = max(after, 0) + 1
        end = min(released, start + PAGE_LIMIT - 1)
        return [
            {"seq": s, "text": inquiry_for_seq(self.seed, s)["text"]}
            for s in range(start, end + 1)
        ]

    def add(self, sink: str, body: Any) -> None:
        with self._lock:
            self.sinks[sink].append(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                },
            )

    def last_processed_seq(self, sink: str) -> int:
        with self._lock:
            last = 0
            for entry in self.sinks[sink]:
                body = entry.get("body")
                if isinstance(body, dict):
                    try:
                        last = max(last, int(body.get("batch_end_seq") or 0))
                    except (TypeError, ValueError):
                        continue
            return last

    def snapshot(self, sink: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.sinks[sink])


class _Handler(BaseHTTPRequestHandler):
    stream: PolicyStream

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/inquiries":
            params = parse_qs(parsed.query)
            try:
                after = int(params.get("after", ["0"])[0])
            except ValueError:
                self._send_json(400, {"error": "after must be an integer"})
                return
            self._send_json(200, self.stream.inquiries_after(after))
            return
        for sink in SINKS:
            if parsed.path == f"/{sink}/last":
                self._send_json(200, {"last_seq": self.stream.last_processed_seq(sink)})
                return
            if parsed.path == f"/{sink}":
                self._send_json(200, self.stream.snapshot(sink))
                return
        self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        sink = parsed.path.lstrip("/")
        if sink not in SINKS:
            self._send_json(404, {"error": f"unknown path {parsed.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "body must be valid JSON"})
            return
        self.stream.add(sink, body)
        self._send_json(200, {"status": "received"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class PolicyFixtureServer:
    def __init__(self, *, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> None:
        self.stream = PolicyStream(seed=seed)
        handler = type("BoundHandler", (_Handler,), {"stream": self.stream})
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="policy-fixture-server",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "PolicyFixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
