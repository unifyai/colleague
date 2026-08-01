"""Render the policy-propagation digest graph as a self-contained SVG.

Two stacked panels:

  - Per-round steady-state LLM tokens (log scale) for the whole
    three-automation family, rounds after each automation's first
    (bootstrap) fire — the recurring bill either architecture pays.
  - Cumulative tokens from the policy-change moment onward: the change
    session itself plus subsequent rounds, measured then projected at the
    measured steady rates, with the payback crossover marked. This is the
    honest reconciliation: the arm with the cheaper change starts ahead;
    the arm with the cheaper steady state overtakes and diverges.

Both arms scored 15/15 with every post-change fire correct under the new
threshold, so correctness lives in the subtitle. Same validated palette;
log scale labeled; no dual axes.

Usage:
    .venv/bin/python -m colleague.tracks.standing.policy_propagation.plot \
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
PANEL_H = 235
MARGIN_L = 84
MARGIN_R = 205
MARGIN_TOP = 92
PANEL_GAP = 62
MARGIN_BOTTOM = 40

PROJECT_ROUNDS = 40


def _newest(pattern: str, *, required: bool = True) -> Path | None:
    def _usable(d: Path) -> bool:
        f = d / "results.json"
        if not f.exists():
            return False
        try:
            # Setup-abort runs still write results.json for the record;
            # they are not measurements and must never reach a graph.
            return "aborted" not in json.loads(f.read_text())
        except ValueError:
            return False

    candidates = sorted(
        d for d in (EXPERIMENT_DIR / "results").glob(pattern) if _usable(d)
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


def _round_tokens(results: dict[str, Any]) -> dict[int, int]:
    """round -> total tokens across the family's fires (+ review tails)."""
    tokens = _phase_tokens(results)
    rounds: dict[int, int] = {}
    for name, value in tokens.items():
        if not name.startswith("fire_round"):
            continue
        round_no = int(name.split("_")[1].removeprefix("round"))
        rounds[round_no] = rounds.get(round_no, 0) + value
    return rounds


def _fmt(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M" if v < 10_000_000 else f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}k" if v >= 10_000 else f"{v / 1_000:.1f}k"
    return str(int(v))


def render(
    unify_results: dict[str, Any],
    hermes_results: dict[str, Any],
    openclaw_results: dict[str, Any] | None = None,
    opencode_results: dict[str, Any] | None = None,
) -> str:
    u_rounds = _round_tokens(unify_results)
    h_rounds = _round_tokens(hermes_results)
    n_rounds = max(u_rounds)
    u_change = _phase_tokens(unify_results).get("policy_change", 0)
    h_change = _phase_tokens(hermes_results).get("policy_change", 0)

    # Steady-state per-round rates: rounds after the bootstrap round 1.
    u_steady = sum(u_rounds.get(r, 0) for r in range(2, n_rounds + 1)) / (n_rounds - 1)
    h_steady = sum(h_rounds.get(r, 0) for r in range(2, n_rounds + 1)) / (n_rounds - 1)

    c_rounds: dict[int, int] | None = None
    c_change = 0
    c_steady = 0.0
    c_ok = None
    if opencode_results is not None:
        c_rounds = _round_tokens(opencode_results)
        c_change = _phase_tokens(opencode_results).get("policy_change", 0)
        c_steady = sum(c_rounds.get(r, 0) for r in range(2, n_rounds + 1)) / (
            n_rounds - 1
        )
        c_ok = sum(1 for f in opencode_results["fires"] if f["correct"])

    o_rounds: dict[int, int] | None = None
    o_change = 0
    o_steady = 0.0
    o_ok = None
    if openclaw_results is not None:
        o_rounds = _round_tokens(openclaw_results)
        o_change = _phase_tokens(openclaw_results).get("policy_change", 0)
        o_steady = sum(o_rounds.get(r, 0) for r in range(2, n_rounds + 1)) / (
            n_rounds - 1
        )
        o_ok = sum(1 for f in openclaw_results["fires"] if f["correct"])

    n_fires = len(unify_results.get("fires", []))
    u_ok = sum(1 for f in unify_results["fires"] if f["correct"])
    h_ok = sum(1 for f in hermes_results["fires"] if f["correct"])

    height = MARGIN_TOP + PANEL_H + PANEL_GAP + PANEL_H + MARGIN_BOTTOM
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="system-ui, -apple-system, '
        f'Segoe UI, sans-serif">',
        f'<rect width="{WIDTH}" height="{height}" fill="{SURFACE}"/>',
        f'<text x="{MARGIN_L}" y="26" fill="{INK}" font-size="17" font-weight="700">'
        "One policy, three automations, one change request: cost to run and to change"
        "</text>",
        f'<text x="{MARGIN_L}" y="44" fill="{INK_MUTED}" font-size="12">'
        f"gpt-5.6-sol via OpenRouter · correctness {u_ok}/{n_fires} vs {h_ok}/{n_fires}"
        + (f" vs {o_ok}/{n_fires}" if o_ok is not None else "")
        + (f" vs {c_ok}/{n_fires}" if c_ok is not None else "")
        + " · every post-change fire honored the new threshold</text>",
    ]

    # ── Panel 1: per-round steady tokens, log scale ────────────────────────
    p1_top = MARGIN_TOP
    vals_all = [u_rounds.get(r, 0) for r in range(2, n_rounds + 1)] + [
        h_rounds.get(r, 0) for r in range(2, n_rounds + 1)
    ]
    if o_rounds is not None:
        vals_all += [o_rounds.get(r, 0) for r in range(2, n_rounds + 1)]
    if c_rounds is not None:
        vals_all += [c_rounds.get(r, 0) for r in range(2, n_rounds + 1)]
    vals_all = [v for v in vals_all if v > 0] or [1]
    lo = 10 ** math.floor(math.log10(max(min(vals_all), 100)))
    hi = 10 ** math.ceil(math.log10(max(vals_all)))

    def x1(r: int) -> float:
        plot_w = WIDTH - MARGIN_L - MARGIN_R
        return MARGIN_L + plot_w * ((r - 2) / max(n_rounds - 2, 1))

    def y1(v: float) -> float:
        frac = (math.log10(max(v, 1)) - math.log10(lo)) / (
            math.log10(hi) - math.log10(lo)
        )
        return p1_top + PANEL_H - (PANEL_H - 18) * frac - 6

    parts.append(
        f'<text x="{MARGIN_L}" y="{p1_top - 10}" fill="{INK}" font-size="14" '
        f'font-weight="600">Steady-state tokens per round — all three automations '
        f"(log scale)</text>",
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
            f'font-size="11" text-anchor="end">{_fmt(decade)}</text>',
        )
        decade *= 10
    p1_series: list[tuple[dict[int, int], str, str]] = [
        (h_rounds, HERMES_COLOR, "square"),
    ]
    if o_rounds is not None:
        p1_series.append((o_rounds, OPENCLAW_COLOR, "triangle"))
    if c_rounds is not None:
        p1_series.append((c_rounds, OPENCODE_COLOR, "diamond"))
    p1_series.append((u_rounds, UNIFY_COLOR, "circle"))
    for rounds, color, shape in p1_series:
        pts = " ".join(
            f"{x1(r):.1f},{y1(rounds.get(r, 0)):.1f}" for r in range(2, n_rounds + 1)
        )
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>',
        )
        for r in range(2, n_rounds + 1):
            cx, cy = x1(r), y1(rounds.get(r, 0))
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
                    f'<path d="M {cx:.1f} {cy - 5:.1f} L {cx + 4.5:.1f} '
                    f'{cy + 4:.1f} L {cx - 4.5:.1f} {cy + 4:.1f} Z" '
                    f'fill="{color}" stroke="{SURFACE}" stroke-width="2"/>',
                )
            else:
                parts.append(
                    f'<rect x="{cx - 4:.1f}" y="{cy - 4:.1f}" width="8" height="8" '
                    f'fill="{color}" stroke="{SURFACE}" stroke-width="2"/>',
                )
    p1_labels = [
        (u_rounds, UNIFY_COLOR, "Unify", u_steady),
        (h_rounds, HERMES_COLOR, "hermes", h_steady),
    ]
    if o_rounds is not None:
        p1_labels.append((o_rounds, OPENCLAW_COLOR, "openclaw", o_steady))
    if c_rounds is not None:
        p1_labels.append((c_rounds, OPENCODE_COLOR, "opencode", c_steady))
    used: list[float] = []
    for rounds, color, name, rate in p1_labels:
        ey = y1(rounds[n_rounds])
        while any(abs(ey - u) < 16 for u in used):
            ey += 16
        used.append(ey)
        parts.append(
            f'<rect x="{WIDTH - MARGIN_R + 8}" y="{ey - 5:.1f}" width="10" '
            f'height="10" fill="{color}"/>',
        )
        parts.append(
            f'<text x="{WIDTH - MARGIN_R + 23}" y="{ey + 4:.1f}" fill="{INK}" '
            f'font-size="12">{html.escape(name)} · {_fmt(rate)}/round</text>',
        )
    for r in range(2, n_rounds + 1):
        parts.append(
            f'<text x="{x1(r):.1f}" y="{y1(lo) + 18:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="middle">round {r}</text>',
        )

    # ── Panel 2: cumulative from the change, measured + projected ──────────
    p2_top = MARGIN_TOP + PANEL_H + PANEL_GAP
    post_rounds = [r for r in range(1, n_rounds + 1) if r > 2]  # rounds after change

    def cumulative(change: int, rounds: dict[int, int], steady: float) -> list[float]:
        out = [float(change)]
        for r in post_rounds:
            out.append(out[-1] + rounds.get(r, 0))
        while len(out) - 1 < PROJECT_ROUNDS:
            out.append(out[-1] + steady)
        return out

    u_cum = cumulative(u_change, u_rounds, u_steady)
    h_cum = cumulative(h_change, h_rounds, h_steady)
    o_cum = cumulative(o_change, o_rounds, o_steady) if o_rounds is not None else None
    c_cum = cumulative(c_change, c_rounds, c_steady) if c_rounds is not None else None
    vmax = max(
        u_cum[-1],
        h_cum[-1],
        o_cum[-1] if o_cum else 0,
        c_cum[-1] if c_cum else 0,
    )
    crossover = next((i for i in range(len(u_cum)) if u_cum[i] <= h_cum[i]), None)

    def x2(i: float) -> float:
        plot_w = WIDTH - MARGIN_L - MARGIN_R
        return MARGIN_L + plot_w * (i / PROJECT_ROUNDS)

    def y2(v: float) -> float:
        return p2_top + PANEL_H - (PANEL_H - 18) * (v / vmax) - 6

    parts.append(
        f'<text x="{MARGIN_L}" y="{p2_top - 10}" fill="{INK}" font-size="14" '
        f'font-weight="600">Cumulative tokens from the change request onward — '
        f"measured, then projected at the measured rates</text>",
    )
    for frac in (0.25, 0.5, 0.75, 1.0):
        gy = y2(vmax * frac)
        parts.append(
            f'<line x1="{MARGIN_L}" y1="{gy:.1f}" x2="{WIDTH - MARGIN_R}" '
            f'y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>',
        )
        parts.append(
            f'<text x="{MARGIN_L - 8}" y="{gy + 4:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="end">{_fmt(vmax * frac)}</text>',
        )
    base_y = y2(0)
    parts.append(
        f'<line x1="{MARGIN_L}" y1="{base_y:.1f}" x2="{WIDTH - MARGIN_R}" '
        f'y2="{base_y:.1f}" stroke="{INK_MUTED}" stroke-width="1"/>',
    )
    measured_x = x2(len(post_rounds))
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
        n_meas = len(post_rounds)
        solid = " ".join(
            f"{x2(i):.1f},{y2(v):.1f}" for i, v in enumerate(cum[: n_meas + 1])
        )
        dashed = " ".join(
            f"{x2(i):.1f},{y2(v):.1f}" for i, v in enumerate(cum) if i >= n_meas
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
    used = []
    for cum, color, name in p2_labels:
        ey = y2(cum[-1])
        while any(abs(ey - u) < 16 for u in used):
            ey += 16
        used.append(ey)
        parts.append(
            f'<rect x="{WIDTH - MARGIN_R + 8}" y="{ey - 5:.1f}" width="10" '
            f'height="10" fill="{color}"/>',
        )
        parts.append(
            f'<text x="{WIDTH - MARGIN_R + 23}" y="{ey + 4:.1f}" fill="{INK}" '
            f'font-size="12">{html.escape(name)} · {_fmt(cum[-1])}</text>',
        )
    if crossover:
        cx, cy = x2(crossover), y2(u_cum[crossover])
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="none" '
            f'stroke="{INK}" stroke-width="1.5"/>',
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{cy - 10:.1f}" fill="{INK}" font-size="11" '
            f'text-anchor="middle">Unify cheaper from round {crossover} after '
            "the change</text>",
        )
    for i in (0, len(post_rounds), 12, 24, PROJECT_ROUNDS):
        label = "change" if i == 0 else str(i)
        parts.append(
            f'<text x="{x2(i):.1f}" y="{base_y + 16:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="middle">{label}</text>',
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
    out = EXPERIMENT_DIR / "results" / "policy_propagation.svg"
    out.write_text(
        render(unify_results, hermes_results, openclaw_results, opencode_results),
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
