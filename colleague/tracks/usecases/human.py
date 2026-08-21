"""Direct human baselines for the measured use-case pages.

Each runner declares a participant surface — the marketing brief in its own
words plus labelled lookup and hand-over forms — so the browser workbench
never shows a URL or a JSON key. The forms compose exactly the ``/get`` and
``/post`` commands a terminal participant would type against the same
fixture; the connection block stays in the sent text for the terminal.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, TextIO

from colleague.tracks.standing.human_legacy import Protocol


def _f(key: str, label: str, kind: str = "text", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "kind": kind, **extra}


def _agency_surface(brief: str) -> dict[str, Any]:
    month_param = {
        "name": "month",
        "label": "Month",
        "kind": "text",
        "hint": "YYYY-MM, e.g. 2026-07",
    }
    client_param = {
        "name": "client_id",
        "label": "Client id",
        "kind": "text",
        "hint": "from the client list",
    }
    campaigns = "One row per campaign; money figures are whole numbers of cents."
    return {
        "title": "Monthly client performance reports",
        "brief": (
            brief
            + "\n\nThe three ad platforms are already connected, and every "
            "money figure is a whole number of cents. When a client's report "
            "is finished, hand it over with the hand-over action below — one "
            "hand-over per client. There is no mail server and no "
            "client-facing channel connected here, so that hand-over is the "
            "whole delivery."
        ),
        "lookups": [
            {"label": "Client list", "description": "Every client, with id, name, vertical and whether revenue is tracked.", "path": "/clients", "params": []},
            {"label": "Google Ads campaigns", "description": campaigns, "path": "/clients/<client_id>/google_ads", "params": [client_param, month_param]},
            {"label": "Meta Ads campaigns", "description": campaigns, "path": "/clients/<client_id>/meta_ads", "params": [client_param, month_param]},
            {"label": "Analytics", "description": campaigns + " Revenue appears for clients that track it.", "path": "/clients/<client_id>/analytics", "params": [client_param, month_param]},
        ],
        "actions": [
            {
                "label": "Hand over a client's report",
                "description": "One per client.",
                "path": "/deliveries",
                "fields": [
                    _f("client_id", "Client id"),
                    _f("month", "Month the report covers", hint="YYYY-MM"),
                    _f("status", "Did you write the report?", "choice", options=["drafted", "blocked"]),
                    _f(
                        "blocked_reason",
                        "If blocked: why (one sentence)",
                        hint="leave empty when drafted",
                        allow_empty=True,
                    ),
                    _f(
                        "flagged",
                        "Campaigns you are flagging",
                        "rows",
                        allow_empty=True,
                        columns=[
                            _f("campaign_id", "Campaign id"),
                            _f("platform", "Platform", "choice", options=["google_ads", "meta_ads"]),
                            _f("reason", "Reason"),
                        ],
                    ),
                    _f("doc_markdown", "The report document", "long"),
                    _f(
                        "draft_email",
                        "Draft email (addressed to me, not the client)",
                        "group",
                        fields=[
                            _f("to", "To", "email"),
                            _f("subject", "Subject"),
                            _f("body", "Body", "long"),
                        ],
                    ),
                ],
            },
        ],
        "hold": None,
        "ask": False,
    }


def _ecommerce_surface(brief: str) -> dict[str, Any]:
    week_params = [
        {"name": "from", "label": "From (a Monday)", "kind": "date", "hint": ""},
        {"name": "to", "label": "To (a Monday)", "kind": "date", "hint": ""},
    ]
    return {
        "title": "Weekly trading review",
        "brief": (
            brief
            + "\n\nThe three platforms are already connected. Every data "
            "lookup takes a from-Monday and a to-Monday and returns one row "
            "per week in that range; history runs about a year back. Money "
            "figures are whole numbers of cents, and rates are in basis "
            "points — 2850 means 28.50%. Slack is not connected here: post "
            "the write-up with the action below, and that post is the whole "
            "hand-over."
        ),
        "lookups": [
            {"label": "Shopify weekly figures", "description": "Orders, revenue, new vs returning customer revenue, repeat purchase rate (basis points) and new customers, per week.", "path": "/shopify/weekly", "params": week_params},
            {"label": "Klaviyo weekly figures", "description": "Campaign revenue, flow revenue and list size, per week.", "path": "/klaviyo/weekly", "params": week_params},
            {"label": "Meta Ads weekly figures", "description": "Ad spend and blended CAC, per week.", "path": "/meta/weekly", "params": week_params},
        ],
        "actions": [
            {
                "label": "Post the write-up",
                "description": "The whole hand-over.",
                "path": "/slack/trading",
                "fields": [
                    _f("week_start", "Monday of the week you are reporting on", "date"),
                    _f("text", "The write-up, exactly as you would post it", "long"),
                    _f("dashboard_url", "Dashboard link"),
                    _f(
                        "flagged",
                        "Metrics you are flagging",
                        "rows",
                        allow_empty=True,
                        columns=[
                            _f("metric", "Metric", "choice", options=["repeat_rate", "blended_cac", "flow_revenue"]),
                            _f("reason", "Reason"),
                        ],
                    ),
                    _f("moved", "Which revenue moved", "choice", options=["new", "returning"]),
                ],
            },
        ],
        "hold": None,
        "ask": False,
    }


def agency_client_reporting(
    *,
    hourly_rate_usd: float,
    participant_id: str,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    results_root: Path | None = None,
) -> int:
    from colleague.tracks.usecases.agency_client_reporting.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
    )
    from colleague.tracks.usecases.agency_client_reporting.protocol import (
        DEFAULT_USECASES_TSX,
        brief_digest,
        extract_brief,
        score_run,
        utterance,
    )

    seed = int(os.environ.get("ACR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("ACR_PORT", DEFAULT_PORT))
    timeout = float(os.environ.get("ACR_PHASE_TIMEOUT_S", "3600"))
    brief_path = Path(os.environ.get("ACR_USECASES_TSX", DEFAULT_USECASES_TSX))
    brief = extract_brief(brief_path)
    fixture = FixtureServer(seed=seed, port=port).start()
    directory = Path(__file__).resolve().parent / "agency_client_reporting"
    p = Protocol(
        name="agency_client_reporting",
        directory=directory,
        fixture=fixture,
        participant_id=participant_id,
        hourly_rate_usd=hourly_rate_usd,
        timeout_s=timeout,
        input_fn=input_fn,
        output=output,
        event_sink=event_sink,
        results_root=results_root,
    )
    try:
        ask = utterance(brief, fixture.base_url)
        p.results.update(
            {
                "seed": seed,
                "anchor": fixture.anchor,
                "brief_sha256": brief_digest(brief),
                "utterance": ask,
            },
        )
        surface = _agency_surface(brief)
        p.session.setup()
        p.setup_one("reporting_cycle", ask, surface=surface)
        before = len(fixture.sink.snapshot())
        fired = p.fire("reporting_cycle", "run_1", surface=surface)
        deliveries = fixture.sink.snapshot()[before:]
        scored = score_run(deliveries, seed=seed, anchor=fixture.anchor)
        active = sum(float(x.get("human_active_seconds") or 0.0) for x in p.phases)
        labour = sum(float(x.get("human_labor_cost_usd") or 0.0) for x in p.phases)
        drafted = int(scored.get("reports_drafted") or 0)
        p.results["fires"].append(
            {
                "fire": 1,
                **fired,
                **scored,
                "correct": (
                    scored.get("detection_status") == "ok"
                    and not scored.get("flags_missed_total")
                    and not scored.get("flags_extra_total")
                ),
                "human_active_seconds_per_drafted_report": (
                    round(active / drafted, 3) if drafted else None
                ),
                "human_labor_cost_per_drafted_report_usd": (
                    round(labour / drafted, 6) if drafted else None
                ),
            },
        )
    finally:
        p.finish()
    return 0


def ecommerce_trading_review(
    *,
    hourly_rate_usd: float,
    participant_id: str,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    results_root: Path | None = None,
) -> int:
    from colleague.tracks.usecases.ecommerce_trading_review.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
    )
    from colleague.tracks.usecases.ecommerce_trading_review.protocol import (
        DEFAULT_USECASES_TSX,
        brief_digest,
        extract_brief,
        score_run,
        utterance,
    )

    seed = int(os.environ.get("ETR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("ETR_PORT", DEFAULT_PORT))
    timeout = float(os.environ.get("ETR_PHASE_TIMEOUT_S", "3600"))
    brief_path = Path(os.environ.get("ETR_USECASES_TSX", DEFAULT_USECASES_TSX))
    brief = extract_brief(brief_path)
    fixture = FixtureServer(seed=seed, port=port).start()
    directory = Path(__file__).resolve().parent / "ecommerce_trading_review"
    p = Protocol(
        name="ecommerce_trading_review",
        directory=directory,
        fixture=fixture,
        participant_id=participant_id,
        hourly_rate_usd=hourly_rate_usd,
        timeout_s=timeout,
        input_fn=input_fn,
        output=output,
        event_sink=event_sink,
        results_root=results_root,
    )
    try:
        ask = utterance(brief, fixture.base_url)
        p.results.update(
            {
                "seed": seed,
                "anchor": fixture.anchor,
                "brief_sha256": brief_digest(brief),
                "utterance": ask,
            },
        )
        surface = _ecommerce_surface(brief)
        p.session.setup()
        p.setup_one("trading_review", ask, surface=surface)
        before = len(fixture.sink.snapshot())
        fired = p.fire("trading_review", "run_1", surface=surface)
        posts = fixture.sink.snapshot()[before:]
        scored = score_run(posts, seed=seed, anchor=fixture.anchor)
        p.results["fires"].append(
            {
                "fire": 1,
                **fired,
                **scored,
                "correct": (
                    scored.get("flags_exact")
                    and scored.get("week_reported") == fixture.anchor
                    and scored.get("splits_new_vs_returning")
                ),
            },
        )
    finally:
        p.finish()
    return 0


RUNNERS: dict[str, Any] = {
    "agency_client_reporting": agency_client_reporting,
    "ecommerce_trading_review": ecommerce_trading_review,
}
