"""The distillation curve: LLM tokens per fire, by purpose, per arm, across `standing`.

One panel per experiment (and per variant), the newest run of each arm.
Every bar is one arm's spend on one fire; the unify bars are split by what
the tokens were for — planning (deciding what to do), verification (checking
it), repair (fixing it) — read from unify's purpose tags by the in-process
ledger. Proxy-metered arms cannot make that distinction and report every
token as planning, which is stated on the figure.

The shape the suite is built to show: an arm that distils pays for planning
once, then verification while trust is being earned, then nothing until
something breaks — and repair only then. An arm that re-derives pays for
planning every fire, forever.

    .venv/bin/python -m colleague.tracks.standing.plot_distillation_curve

Writes ``colleague/tracks/standing/distillation_curve.svg``. Experiments
whose fires are not a single numbered series (`policy_propagation` fires
three automations a round) are left out; their cost tables are in their own
READMEs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague.tracks.standing.series.plot import (
    ARM_COLOR,
    ARM_ORDER,
    GRID,
    INK,
    INK_MUTED,
    PURPOSE_SHADE,
    SURFACE,
    _esc,
    _shade,
    fire_series,
    latest_runs,
    n_fires,
)
from colleague.tracks.standing.series.report import PURPOSES

STANDING_DIR = Path(__file__).resolve().parent
OUT_PATH = STANDING_DIR / "distillation_curve.svg"

#: (experiment directory, variant, panel title), in the order they are drawn.
PANELS: list[tuple[str, str | None, str]] = [
    ("recurring_report", None, "recurring_report — weekly report"),
    ("drift_recovery", None, "drift_recovery — field renamed before fire 5"),
    ("semantic_triage", None, "semantic_triage — judgement substep"),
    (
        "silent_drift",
        "units",
        "silent_drift[units] — amount changes units before fire 5",
    ),
    ("silent_drift", "page", "silent_drift[page] — page cap halves before fire 5"),
    ("edge_week", "empty", "edge_week[empty] — week 5 has no invoices"),
    (
        "edge_week",
        "duplicate",
        "edge_week[duplicate] — week 5 serves one invoice twice",
    ),
    ("edge_week", "currency", "edge_week[currency] — week 5 has a GBP invoice"),
    (
        "edge_week",
        "no_email",
        "edge_week[no_email] — week 5 has an invoice with no contact",
    ),
    ("repair_locality", None, "repair_locality — refunds renamed before fire 5"),
    (
        "change_without_regression",
        None,
        "change_without_regression — a column added before fire 4",
    ),
]

WIDTH = 960
MARGIN_L = 90
MARGIN_R = 30
PANEL_H = 150
PANEL_GAP = 46
TOP = 96
BOTTOM = 70


def _panels_with_runs() -> list[tuple[str, dict[str, dict[str, Any]]]]:
    out = []
    for name, variant, title in PANELS:
        runs = latest_runs(STANDING_DIR / name, variant=variant)
        if runs:
            out.append((title, runs))
    return out


def main() -> int:
    panels = _panels_with_runs()
    if not panels:
        print("[plot] no standing runs found; nothing to draw")
        return 1
    height = TOP + len(panels) * (PANEL_H + PANEL_GAP) + BOTTOM
    plot_w = WIDTH - MARGIN_L - MARGIN_R
    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" font-family="Inter, Helvetica, Arial, sans-serif">',
        f'<rect width="{WIDTH}" height="{height}" fill="{SURFACE}"/>',
        f'<text x="{MARGIN_L}" y="34" font-size="18" font-weight="600" fill="{INK}">The distillation curve — LLM tokens per fire, by purpose, per arm</text>',
        f'<text x="{MARGIN_L}" y="56" font-size="12" fill="{INK_MUTED}">Newest run of each arm per experiment. Shades split unify\'s spend into planning / verification / repair; proxy-metered arms report every token as planning.</text>',
    ]
    # Legend.
    lx, ly = MARGIN_L, 80
    for arm in ARM_ORDER:
        svg.append(
            f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{ARM_COLOR[arm]}"/>',
        )
        svg.append(
            f'<text x="{lx + 16}" y="{ly}" font-size="11" fill="{INK}">{arm}</text>',
        )
        lx += 20 + 8 * len(arm) + 16
    lx += 24
    for purpose in PURPOSES:
        svg.append(
            f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{_shade(ARM_COLOR["unify"], PURPOSE_SHADE[purpose])}"/>',
        )
        svg.append(
            f'<text x="{lx + 16}" y="{ly}" font-size="11" fill="{INK}">unify: {purpose}</text>',
        )
        lx += 20 + 8 * (len(purpose) + 7) + 16

    for p, (title, runs) in enumerate(panels):
        top = TOP + p * (PANEL_H + PANEL_GAP)
        bottom = top + PANEL_H
        arms = [a for a in ARM_ORDER if a in runs]
        series = {a: fire_series(runs[a]) for a in arms}
        total = max(n_fires(runs[a]) for a in arms)
        slot = plot_w / max(1, total)
        bar_w = max(3.0, (slot - 8) / max(1, len(arms)))
        vmax = max(
            [1] + [int(r["tokens"].get("total", 0)) for a in arms for r in series[a]],
        )
        svg.append(
            f'<text x="{MARGIN_L}" y="{top - 10}" font-size="13" font-weight="600" fill="{INK}">{_esc(title)}</text>',
        )
        for frac in (0.0, 0.5, 1.0):
            y = bottom - PANEL_H * frac
            svg.append(
                f'<line x1="{MARGIN_L}" y1="{y:.1f}" x2="{WIDTH - MARGIN_R}" y2="{y:.1f}" stroke="{GRID}"/>',
            )
            svg.append(
                f'<text x="{MARGIN_L - 8}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="{INK_MUTED}">{int(vmax * frac):,}</text>',
            )
        for i in range(1, total + 1):
            x0 = MARGIN_L + slot * (i - 1) + 4
            svg.append(
                f'<text x="{MARGIN_L + slot * (i - 0.5):.1f}" y="{bottom + 14}" font-size="10" text-anchor="middle" fill="{INK_MUTED}">{i}</text>',
            )
            for k, arm in enumerate(arms):
                row = next((r for r in series[arm] if r["fire"] == i), None)
                if row is None:
                    continue
                x = x0 + k * bar_w
                y = bottom
                for purpose in PURPOSES:
                    bucket = row["tokens"].get(purpose) or {}
                    amount = int(bucket.get("prompt", 0)) + int(
                        bucket.get("completion", 0),
                    )
                    if amount <= 0:
                        continue
                    h = PANEL_H * amount / vmax
                    y -= h
                    svg.append(
                        f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 1:.1f}" height="{h:.1f}" fill="{_shade(ARM_COLOR[arm], PURPOSE_SHADE[purpose])}"><title>{arm} fire {i} {purpose}: {amount:,}</title></rect>',
                    )
                # A hollow tick marks a fire the arm did not get right, so cost
                # and correctness read together.
                if row["outcome"] != "correct":
                    svg.append(
                        f'<text x="{x + bar_w / 2:.1f}" y="{bottom - 2}" font-size="9" text-anchor="middle" fill="{ARM_COLOR[arm]}">{"◐" if row["outcome"] == "held" else "×"}</text>',
                    )
    svg.append(
        f'<text x="{MARGIN_L}" y="{height - 30}" font-size="10" fill="{INK_MUTED}">× a fire the arm got wrong; ◐ a fire it held with a reason. Bars are the newest committed run per arm; an experiment with no runs yet is not drawn.</text>',
    )
    svg.append("</svg>")
    OUT_PATH.write_text("\n".join(svg), encoding="utf-8")
    print(f"[plot] wrote {OUT_PATH} ({len(panels)} panels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
