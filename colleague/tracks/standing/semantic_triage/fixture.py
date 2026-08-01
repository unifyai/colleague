"""Inquiry-stream fixture for the semantic triage benchmark.

A deterministic, seeded stream of natural-language customer inquiries with
golden category labels. The stream is seq-keyed with the sink as the cursor
(same shape as drift_recovery's fixture), so fires are timing-independent
and every fire has fresh, deterministic work.

The templates are written so that classification requires reading for
meaning, not keyword spotting: each category includes phrasings that
lexically overlap with other categories (a bug report about the *payment*
screen, an *invoice* question that is not a refund, a pricing question that
never says "buy"). A focused LLM call classifies them near-perfectly; a
keyword heuristic measurably cannot. Golden labels are certain by
construction — the generator picks the category first, then renders text
from that category's templates.

Endpoints:
    GET  /health                      -> {"status": "ok"}
    GET  /inquiries?after=N           -> up to 200 inquiries with seq > N, each {seq, text}
    GET  /batches/last                -> {"last_seq": highest triaged seq (0 if none)}
    POST /batches                     -> stores the JSON body
    GET  /batches                     -> all stored batches (with receipt metadata)
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
PAGE_LIMIT = 200

DEFAULT_SEED = 20260731
DEFAULT_PORT = 8128

_PRODUCTS = (
    "the analytics dashboard",
    "the mobile app",
    "the API",
    "the browser extension",
    "the desktop client",
)
_AMOUNTS = ("$19", "$49", "$120", "$310", "$999")
_COUNTS = ("15", "40", "80", "200", "500")

# Each template is unambiguous to a careful reader, but the vocabulary
# deliberately crosses category lines so shallow keyword rules misfire.
_TEMPLATES: dict[str, tuple[str, ...]] = {
    "refund": (
        "I was charged twice for {product} last week and want the second charge reversed.",
        "My card was billed {amount} after I cancelled — please send my money back.",
        "The upgrade never activated but the payment went through; I'd like that payment returned.",
        "You billed me {amount} for a plan I downgraded out of. Can you credit it back to my card?",
        "I bought the annual plan by mistake instead of monthly — please undo that charge.",
        "Order shows delivered but nothing ever arrived; I want my {amount} back.",
        "I was double-billed on the same invoice and expect the duplicate to be repaid.",
        "Please reverse yesterday's charge of {amount}; I did not authorize it.",
        "Cancelled during the trial but still got charged — I'd like that amount back on my card.",
        "The add-on I paid {amount} for was never enabled. I want that payment back, not a fix.",
    ),
    "bug": (
        "The payment screen freezes every time I enter my card number.",
        "Checkout crashes with an error mentioning refund tokens whenever I apply a coupon.",
        "{product} shows a blank page right after login since this morning.",
        "Exporting my invoice history to CSV produces a corrupted file.",
        "The pricing page never finishes loading on Safari — endless spinner.",
        "Push notifications from {product} arrive three hours late.",
        "Search returns no results even for items I can see on screen.",
        "My account balance displays {amount} less than the transactions add up to — the math on screen is wrong.",
        "Uploading a photo makes {product} crash back to the home screen.",
        "The upgrade button does nothing when clicked; the console shows a script error.",
    ),
    "sales": (
        "Do you offer discounts if we purchase {count} seats for our team?",
        "We're comparing vendors this quarter — can someone walk us through pricing tiers?",
        "What would it cost to move from the starter plan to enterprise?",
        "Can we schedule a demo of {product} for our procurement committee?",
        "Is there a nonprofit rate? We'd roll it out to {count} volunteers.",
        "Our contract is up for renewal and we want to talk about expanding usage.",
        "Does the enterprise tier include priority support, and what does it run per year?",
        "We need invoicing on net-60 terms before we can buy — who do I talk to?",
        "Looking to bundle {product} with the API for {count} users; what's the best deal?",
        "My boss asked me to get a quote for company-wide adoption.",
    ),
    "other": (
        "Where can I download my invoice history for our accountant?",
        "What are your support hours over the holidays?",
        "How do I change which email address gets billing receipts?",
        "Is there a status page I can watch during your maintenance windows?",
        "How do I add a teammate as an admin on our workspace?",
        "Can I get a copy of your security and compliance documentation?",
        "What's the difference between archiving and deleting a project?",
        "How do I turn off the weekly digest emails?",
        "Does {product} support two-factor authentication, and where do I enable it?",
        "My name is spelled wrong on the account — where do I edit my profile?",
    ),
}


def _h(seed: int, *parts: Any) -> int:
    payload = ":".join([str(seed), *map(str, parts)]).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def inquiry_for_seq(seed: int, seq: int) -> dict[str, Any]:
    """The unique inquiry at position ``seq`` (1-based), with its golden label."""
    h = _h(seed, "inquiry", seq)
    category = CATEGORIES[h % len(CATEGORIES)]
    templates = _TEMPLATES[category]
    template = templates[(h >> 8) % len(templates)]
    text = template.format(
        product=_PRODUCTS[(h >> 16) % len(_PRODUCTS)],
        amount=_AMOUNTS[(h >> 24) % len(_AMOUNTS)],
        count=_COUNTS[(h >> 32) % len(_COUNTS)],
    )
    return {"seq": seq, "text": text, "category": category}


def golden_labels(seed: int, start_seq: int, end_seq: int) -> dict[int, str]:
    return {
        seq: inquiry_for_seq(seed, seq)["category"]
        for seq in range(start_seq, end_seq + 1)
    }


def score_triage_batch(
    actual: Any,
    *,
    seed: int,
    start_seq: int,
    end_seq: int,
) -> dict[str, Any]:
    """Score a posted batch: contract exactness plus per-item accuracy."""
    if not isinstance(actual, dict):
        return {
            "contract_correct": False,
            "accuracy": 0.0,
            "checks": {"is_json_object": False},
        }
    checks: dict[str, bool] = {"is_json_object": True}
    checks["batch_start_seq"] = actual.get("batch_start_seq") == start_seq
    checks["batch_end_seq"] = actual.get("batch_end_seq") == end_seq
    checks["no_extra_keys"] = not (
        set(actual) - {"batch_start_seq", "batch_end_seq", "classifications"}
    )

    raw = actual.get("classifications")
    per_item: dict[int, str] = {}
    well_formed = isinstance(raw, list)
    if well_formed:
        for entry in raw:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("seq"), int)
                or entry.get("seq") in per_item
                or entry.get("category") not in CATEGORIES
            ):
                well_formed = False
                break
            per_item[entry["seq"]] = entry["category"]
    checks["classifications_well_formed"] = well_formed
    checks["covers_all_seqs_exactly_once"] = well_formed and set(per_item) == set(
        range(start_seq, end_seq + 1),
    )

    golden = golden_labels(seed, start_seq, end_seq)
    graded = [
        (seq, per_item.get(seq), golden[seq]) for seq in range(start_seq, end_seq + 1)
    ]
    correct_items = sum(1 for _, got, want in graded if got == want)
    total_items = len(graded)
    return {
        "contract_correct": all(checks.values()),
        "accuracy": round(correct_items / total_items, 4) if total_items else 0.0,
        "correct_items": correct_items,
        "total_items": total_items,
        "misclassified": [
            {"seq": seq, "got": got, "want": want}
            for seq, got, want in graded
            if got != want
        ],
        "checks": checks,
    }


@dataclass
class InquiryStream:
    """Mutable fixture state shared between the HTTP handler and the harness."""

    seed: int = DEFAULT_SEED
    released_seq: int = 0
    batches: list[dict[str, Any]] = field(default_factory=list)
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
            {
                k: v
                for k, v in inquiry_for_seq(self.seed, seq).items()
                if k != "category"
            }
            for seq in range(start, end + 1)
        ]

    def add_batch(self, body: Any) -> None:
        with self._lock:
            self.batches.append(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                },
            )

    def last_processed_seq(self) -> int:
        with self._lock:
            last = 0
            for entry in self.batches:
                body = entry.get("body")
                if isinstance(body, dict):
                    try:
                        last = max(last, int(body.get("batch_end_seq") or 0))
                    except (TypeError, ValueError):
                        continue
            return last

    def snapshot_batches(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.batches)


class _Handler(BaseHTTPRequestHandler):
    stream: InquiryStream

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
        if parsed.path == "/batches/last":
            self._send_json(200, {"last_seq": self.stream.last_processed_seq()})
            return
        if parsed.path == "/batches":
            self._send_json(200, self.stream.snapshot_batches())
            return
        self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/batches":
            self._send_json(404, {"error": f"unknown path {parsed.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "body must be valid JSON"})
            return
        self.stream.add_batch(body)
        self._send_json(200, {"status": "received"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class TriageFixtureServer:
    """In-process fixture server bound to 127.0.0.1."""

    def __init__(self, *, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> None:
        self.stream = InquiryStream(seed=seed)
        handler = type("BoundHandler", (_Handler,), {"stream": self.stream})
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="triage-fixture-server",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "TriageFixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
