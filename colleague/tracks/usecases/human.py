"""Human operator/builder baselines for the measured use-case pages."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from colleague.tracks.standing.human_legacy import Protocol


def agency_client_reporting(
    *,
    mode: str,
    hourly_rate_usd: float,
    participant_id: str,
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
        mode=mode,
        participant_id=participant_id,
        hourly_rate_usd=hourly_rate_usd,
        timeout_s=timeout,
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
        p.session.setup()
        p.setup_one("reporting_cycle", ask)
        before = len(fixture.sink.snapshot())
        fired = p.fire("reporting_cycle", "run_1")
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
    mode: str,
    hourly_rate_usd: float,
    participant_id: str,
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
        mode=mode,
        participant_id=participant_id,
        hourly_rate_usd=hourly_rate_usd,
        timeout_s=timeout,
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
        p.session.setup()
        p.setup_one("trading_review", ask)
        before = len(fixture.sink.snapshot())
        fired = p.fire("trading_review", "run_1")
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
