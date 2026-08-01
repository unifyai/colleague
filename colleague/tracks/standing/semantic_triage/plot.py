"""Render the semantic-triage digest graph as a self-contained SVG.

Two stacked panels over fires 1..N:

  - Per-fire LLM tokens, log scale (the gap is orders of magnitude): the
    hermes agent-loop line stays flat at its per-fire boot cost; the unify
    line drops to a single focused ``query_llm`` call after fire 1's review
    attaches the stored function.
  - Cumulative tokens including each arm's setup, with a clearly-labeled
    dashed projection at the measured steady-state rates and the crossover
    fire marked.

Accuracy tied at 100% for both arms in the measured runs, so it lives in
the subtitle rather than a panel. Colors are the suite's validated pair;
log scale is explicitly labeled; no dual axes.

Usage:
    .venv/bin/python -m colleague.tracks.standing.semantic_triage.plot \
        [unify_results hermes_results [openclaw_results]]
"""

from __future__ import annotations

import html
import json
import math
import sys
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

SURFACE = "#fcfcfb"
INK = "#1a1a19"
INK_MUTED = "#6f6e6a"
GRID = "#e8e7e4"
UNIFY_COLOR = "#2a78d6"
HERMES_COLOR = "#eb6834"
OPENCLAW_COLOR = "#009E73"
OPENCODE_COLOR = "#7B52AB"

WIDTH = 860
PANEL_H = 240
MARGIN_L = 84
MARGIN_R = 195
MARGIN_TOP = 92
PANEL_GAP = 60
MARGIN_BOTTOM = 40

PROJECT_TO_FIRE = 72  # three days of hourly fires


def _newest(pattern: str, *, required: bool = True) -> Path | None:
    candidates = sorted(
        d
        for d in (EXPERIMENT_DIR / "results").glob(pattern)
        if (d / "results.json").exists()
    )
    if not candidates:
        if required:
            raise SystemExit(f"no results matching {pattern}")
        return None
    return candidates[-1]


def _phase_tokens(results: dict[str, Any]) -> dict[str, int]:
    return {
        p["name"]: int(p.get("prompt_tokens") or 0)
        + int(p.get("completion_tokens") or 0)
        for p in results.get("phases", [])
    }


def _per_fire(results: dict[str, Any]) -> list[int]:
    tokens = _phase_tokens(results)
    n = int(results["n_fires"])
    return [
        tokens.get(f"fire_{i}", 0) + tokens.get(f"fire_{i}_review", 0)
        for i in range(1, n + 1)
    ]


def _fmt_tokens(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}k" if v >= 10_000 else f"{v / 1_000:.1f}k"
    return str(int(v))


def _x(i: float, n: int) -> float:
    plot_w = WIDTH - MARGIN_L - MARGIN_R
    return MARGIN_L + plot_w * (i / n)


def render(
    unify_results: dict[str, Any],
    hermes_results: dict[str, Any],
    openclaw_results: dict[str, Any] | None = None,
    opencode_results: dict[str, Any] | None = None,
) -> str:
    n = int(unify_results["n_fires"])
    u_fires = _per_fire(unify_results)
    h_fires = _per_fire(hermes_results)
    u_setup = _phase_tokens(unify_results).get("setup", 0)
    h_setup = _phase_tokens(hermes_results).get("setup", 0)

    # Measured steady-state rates: unify after the fire-1 distillation,
    # hermes across all fires (its per-fire cost is flat from fire 1).
    u_steady = sum(u_fires[1:]) / max(len(u_fires) - 1, 1)
    h_steady = sum(h_fires) / len(h_fires)

    c_fires: list[int] | None = None
    c_setup = 0
    c_steady = 0.0
    c_acc = None
    if opencode_results is not None:
        c_fires = _per_fire(opencode_results)
        c_setup = _phase_tokens(opencode_results).get("setup", 0)
        c_steady = sum(c_fires) / len(c_fires)
        c_acc = sum(float(f["accuracy"]) for f in opencode_results["fires"]) / n

    o_fires: list[int] | None = None
    o_setup = 0
    o_steady = 0.0
    o_acc = None
    if openclaw_results is not None:
        o_fires = _per_fire(openclaw_results)
        o_setup = _phase_tokens(openclaw_results).get("setup", 0)
        o_steady = sum(o_fires) / len(o_fires)
        o_acc = sum(float(f["accuracy"]) for f in openclaw_results["fires"]) / n

    u_items = sum(int(f.get("total_items") or 0) or 12 for f in unify_results["fires"])
    u_acc = sum(float(f["accuracy"]) for f in unify_results["fires"]) / n
    h_acc = sum(float(f["accuracy"]) for f in hermes_results["fires"]) / n

    height = MARGIN_TOP + PANEL_H + PANEL_GAP + PANEL_H + MARGIN_BOTTOM
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="system-ui, -apple-system, '
        f'Segoe UI, sans-serif">',
        f'<rect width="{WIDTH}" height="{height}" fill="{SURFACE}"/>',
        f'<text x="{MARGIN_L}" y="26" fill="{INK}" font-size="17" font-weight="700">'
        "Recurring work with a judgment step: what every single firing costs"
        "</text>",
        f'<text x="{MARGIN_L}" y="44" fill="{INK_MUTED}" font-size="12">'
        f"One natural-language request · gpt-5.6-sol via OpenRouter · accuracy "
        f"{u_acc:.0%} vs {h_acc:.0%}"
        + (f" vs {o_acc:.0%}" if o_acc is not None else "")
        + (f" vs {c_acc:.0%}" if c_acc is not None else "")
        + f" on {u_items} inquiries each</text>",
    ]

    # ── Panel 1: per-fire tokens, log scale ────────────────────────────────
    p1_top = MARGIN_TOP
    all_fire_vals = u_fires + h_fires + (o_fires or []) + (c_fires or [])
    all_fire_vals = [v for v in all_fire_vals if v > 0] or [1]
    lo = 10 ** math.floor(math.log10(max(min(all_fire_vals), 100)))
    hi = 10 ** math.ceil(math.log10(max(all_fire_vals)))

    def y1(v: float) -> float:
        frac = (math.log10(max(v, 1)) - math.log10(lo)) / (
            math.log10(hi) - math.log10(lo)
        )
        return p1_top + PANEL_H - (PANEL_H - 18) * frac - 6

    parts.append(
        f'<text x="{MARGIN_L}" y="{p1_top - 10}" fill="{INK}" font-size="14" '
        f'font-weight="600">Per-fire LLM tokens (log scale)</text>',
    )
    decade = lo
    while decade <= hi:
        gy = y1(decade)
        parts.append(
            f'<line x1="{MARGIN_L}" y1="{gy:.1f}" x2="{WIDTH - MARGIN_R}" '
            f'y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>',
        )
        parts.append(
            f'<text x="{MARGIN_L - 8}" y="{gy + 4:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="end">{_fmt_tokens(decade)}</text>',
        )
        decade *= 10

    p1_series: list[tuple[list[int], str, str]] = [
        (h_fires, HERMES_COLOR, "square"),
    ]
    if o_fires is not None:
        p1_series.append((o_fires, OPENCLAW_COLOR, "triangle"))
    if c_fires is not None:
        p1_series.append((c_fires, OPENCODE_COLOR, "diamond"))
    p1_series.append((u_fires, UNIFY_COLOR, "circle"))
    for vals, color, shape in p1_series:
        pts = " ".join(f"{_x(i + 1, n):.1f},{y1(v):.1f}" for i, v in enumerate(vals))
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>',
        )
        for i, v in enumerate(vals):
            cx, cy = _x(i + 1, n), y1(v)
            if shape == "circle":
                parts.append(
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{color}" '
                    f'stroke="{SURFACE}" stroke-width="2"/>',
                )
            elif shape == "diamond":
                parts.append(
                    f'<path d="M {cx:.1f} {cy - 5:.1f} L {cx + 5:.1f} {cy:.1f} '
                    f'L {cx:.1f} {cy + 5:.1f} L {cx - 5:.1f} {cy:.1f} Z" '
                    f'fill="{color}" stroke="{SURFACE}" stroke-width="2"/>',
                )
            elif shape == "triangle":
                parts.append(
                    f'<path d="M {cx:.1f} {cy - 5:.1f} L {cx + 4.5:.1f} {cy + 4:.1f} '
                    f'L {cx - 4.5:.1f} {cy + 4:.1f} Z" fill="{color}" '
                    f'stroke="{SURFACE}" stroke-width="2"/>',
                )
            else:
                parts.append(
                    f'<rect x="{cx - 4:.1f}" y="{cy - 4:.1f}" width="8" height="8" '
                    f'fill="{color}" stroke="{SURFACE}" stroke-width="2"/>',
                )

    p1_labels = [
        (u_fires, UNIFY_COLOR, "Unify", u_steady),
        (h_fires, HERMES_COLOR, "hermes", h_steady),
    ]
    if o_fires is not None:
        p1_labels.append((o_fires, OPENCLAW_COLOR, "openclaw", o_steady))
    if c_fires is not None:
        p1_labels.append((c_fires, OPENCODE_COLOR, "opencode", c_steady))
    used_p1_ys: list[float] = []
    for vals, color, name, value in p1_labels:
        ey = y1(vals[-1])
        while any(abs(ey - u) < 16 for u in used_p1_ys):
            ey += 16
        used_p1_ys.append(ey)
        parts.append(
            f'<rect x="{WIDTH - MARGIN_R + 8}" y="{ey - 5:.1f}" width="10" '
            f'height="10" fill="{color}"/>',
        )
        parts.append(
            f'<text x="{WIDTH - MARGIN_R + 23}" y="{ey + 4:.1f}" fill="{INK}" '
            f'font-size="12">{html.escape(name)} · {_fmt_tokens(value)}/fire</text>',
        )
    parts.append(
        f'<text x="{_x(1, n):.1f}" y="{y1(u_fires[0]) - 12:.1f}" fill="{INK_MUTED}" '
        f'font-size="11" text-anchor="middle">fire 1 distills the function</text>',
    )

    # ── Panel 2: cumulative tokens with projection ─────────────────────────
    p2_top = MARGIN_TOP + PANEL_H + PANEL_GAP

    def cumulative(setup: int, fires: list[int], steady: float) -> list[float]:
        out = [float(setup)]
        for v in fires:
            out.append(out[-1] + v)
        while len(out) - 1 < PROJECT_TO_FIRE:
            out.append(out[-1] + steady)
        return out

    u_cum = cumulative(u_setup, u_fires, u_steady)
    h_cum = cumulative(h_setup, h_fires, h_steady)
    o_cum = cumulative(o_setup, o_fires, o_steady) if o_fires is not None else None
    c_cum = cumulative(c_setup, c_fires, c_steady) if c_fires is not None else None
    vmax = max(
        u_cum[-1],
        h_cum[-1],
        o_cum[-1] if o_cum else 0,
        c_cum[-1] if c_cum else 0,
    )

    crossover = next(
        (i for i in range(len(u_cum)) if u_cum[i] <= h_cum[i]),
        None,
    )

    def y2(v: float) -> float:
        return p2_top + PANEL_H - (PANEL_H - 18) * (v / vmax) - 6

    def x2(i: float) -> float:
        plot_w = WIDTH - MARGIN_L - MARGIN_R
        return MARGIN_L + plot_w * (i / PROJECT_TO_FIRE)

    parts.append(
        f'<text x="{MARGIN_L}" y="{p2_top - 10}" fill="{INK}" font-size="14" '
        f'font-weight="600">Cumulative LLM tokens — measured through fire {n}, '
        f"then projected at the measured per-fire rates</text>",
    )
    for frac in (0.25, 0.5, 0.75, 1.0):
        gy = y2(vmax * frac)
        parts.append(
            f'<line x1="{MARGIN_L}" y1="{gy:.1f}" x2="{WIDTH - MARGIN_R}" '
            f'y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>',
        )
        parts.append(
            f'<text x="{MARGIN_L - 8}" y="{gy + 4:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="end">{_fmt_tokens(vmax * frac)}</text>',
        )
    base_y = y2(0)
    parts.append(
        f'<line x1="{MARGIN_L}" y1="{base_y:.1f}" x2="{WIDTH - MARGIN_R}" '
        f'y2="{base_y:.1f}" stroke="{INK_MUTED}" stroke-width="1"/>',
    )
    measured_x = x2(n)
    parts.append(
        f'<line x1="{measured_x:.1f}" y1="{p2_top - 2}" x2="{measured_x:.1f}" '
        f'y2="{base_y:.1f}" stroke="{INK_MUTED}" stroke-width="1" '
        f'stroke-dasharray="4 4"/>',
    )
    parts.append(
        f'<text x="{measured_x + 6:.1f}" y="{p2_top + 10}" fill="{INK_MUTED}" '
        f'font-size="11">measured | projected</text>',
    )

    p2_series: list[tuple[list[float], str]] = [(h_cum, HERMES_COLOR)]
    if o_cum is not None:
        p2_series.append((o_cum, OPENCLAW_COLOR))
    if c_cum is not None:
        p2_series.append((c_cum, OPENCODE_COLOR))
    p2_series.append((u_cum, UNIFY_COLOR))
    for cum, color in p2_series:
        solid = " ".join(f"{x2(i):.1f},{y2(v):.1f}" for i, v in enumerate(cum[: n + 1]))
        dashed = " ".join(
            f"{x2(i):.1f},{y2(v):.1f}" for i, v in enumerate(cum) if i >= n
        )
        parts.append(
            f'<polyline points="{solid}" fill="none" stroke="{color}" stroke-width="2"/>',
        )
        parts.append(
            f'<polyline points="{dashed}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-dasharray="5 5" opacity="0.75"/>',
        )

    p2_labels = [
        (u_cum, UNIFY_COLOR, "Unify"),
        (h_cum, HERMES_COLOR, "hermes"),
    ]
    if o_cum is not None:
        p2_labels.append((o_cum, OPENCLAW_COLOR, "openclaw"))
    if c_cum is not None:
        p2_labels.append((c_cum, OPENCODE_COLOR, "opencode"))
    used_ys: list[float] = []
    for cum, color, name in p2_labels:
        ey = y2(cum[-1])
        while any(abs(ey - u) < 16 for u in used_ys):
            ey += 16
        used_ys.append(ey)
        parts.append(
            f'<rect x="{WIDTH - MARGIN_R + 8}" y="{ey - 5:.1f}" width="10" '
            f'height="10" fill="{color}"/>',
        )
        parts.append(
            f'<text x="{WIDTH - MARGIN_R + 23}" y="{ey + 4:.1f}" fill="{INK}" '
            f'font-size="12">{html.escape(name)} · {_fmt_tokens(cum[-1])} @ fire '
            f"{PROJECT_TO_FIRE}</text>",
        )
    if crossover is not None and crossover > 0:
        cx = x2(crossover)
        cy = y2(u_cum[crossover])
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="none" '
            f'stroke="{INK}" stroke-width="1.5"/>',
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{cy - 10:.1f}" fill="{INK}" font-size="11" '
            f'text-anchor="middle">Unify cheaper from fire {crossover}</text>',
        )

    for i in (1, n, 24, 48, PROJECT_TO_FIRE):
        parts.append(
            f'<text x="{x2(i):.1f}" y="{base_y + 16:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="middle">{i}</text>',
        )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    openclaw_dir: Path | None
    opencode_dir: Path | None
    if len(sys.argv) >= 3:
        unify_dir, hermes_dir = Path(sys.argv[1]), Path(sys.argv[2])
        openclaw_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else None
        opencode_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    else:
        unify_dir, hermes_dir = _newest("*-unify"), _newest("*-hermes")
        openclaw_dir = _newest("*-openclaw", required=False)
        opencode_dir = _newest("*-opencode", required=False)
    unify_results = json.loads((unify_dir / "results.json").read_text())
    hermes_results = json.loads((hermes_dir / "results.json").read_text())
    openclaw_results = (
        json.loads((openclaw_dir / "results.json").read_text())
        if openclaw_dir is not None
        else None
    )
    opencode_results = (
        json.loads((opencode_dir / "results.json").read_text())
        if opencode_dir is not None
        else None
    )
    out = EXPERIMENT_DIR / "results" / "semantic_triage.svg"
    out.write_text(
        render(unify_results, hermes_results, openclaw_results, opencode_results),
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
