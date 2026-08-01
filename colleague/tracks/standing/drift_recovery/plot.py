"""Render the drift-recovery digest graph as a self-contained SVG.

Two stacked panels over a shared x-axis (setup, then fires 1..N):

  - Reliability: cumulative exactly-correct deliveries per system.
  - Cost: cumulative LLM tokens per system (prompt + completion; the same
    provider-reported numbers both arms were metered on).

Never a dual axis: two measures, two panels. Series colors are the validated
categorical pair from the benchmark suite's palette (blue #2a78d6 = unify,
orange #eb6834 = hermes, green #009E73 = openclaw) with distinct marker
shapes as secondary encoding; text wears ink colors, never series colors.

Usage:
    .venv/bin/python -m colleague.tracks.standing.drift_recovery.plot \
        [unify_results hermes_results [openclaw_results]]

Defaults to the newest ``results/*-unify``, ``results/*-hermes`` and (when
present) ``results/*-openclaw`` runs and writes
``results/drift_recovery.svg``.
"""

from __future__ import annotations

import html
import json
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
MARGIN_L = 78
MARGIN_R = 185
MARGIN_TOP = 88
PANEL_GAP = 56
MARGIN_BOTTOM = 46


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


def _series_unattended(results: dict[str, Any]) -> tuple[list[int], list[int]] | None:
    """The hermes counterfactual without the operator: measured fires up to the
    operator fix, then the deterministic continuation — a no_agent script has
    no model in the loop, so without intervention it keeps failing identically
    and its cost line stays flat. Returns None when no operator fix occurred."""
    op = results.get("operator_fix")
    if not isinstance(op, dict):
        return None
    fix_before = int(op.get("before_fire") or 0)
    n_fires = int(results["n_fires"])
    tokens_by_phase = _phase_tokens(results)
    fires = {int(f["fire"]): f for f in results.get("fires", [])}
    cum_correct = [0]
    cum_tokens = [tokens_by_phase.get("setup", 0)]
    for i in range(1, n_fires + 1):
        fire_tokens = tokens_by_phase.get(f"fire_{i}", 0) if i < fix_before else 0
        correct = bool(fires.get(i, {}).get("correct")) if i < fix_before else False
        cum_tokens.append(cum_tokens[-1] + fire_tokens)
        cum_correct.append(cum_correct[-1] + (1 if correct else 0))
    return cum_correct, cum_tokens


def _series(results: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Cumulative (correct_deliveries, tokens) at x = 0 (setup) .. N (fires)."""
    n_fires = int(results["n_fires"])
    tokens_by_phase = _phase_tokens(results)
    fires = {int(f["fire"]): f for f in results.get("fires", [])}

    operator_fix_before = None
    if isinstance(results.get("operator_fix"), dict):
        operator_fix_before = int(results["operator_fix"].get("before_fire") or 0)

    cum_correct = [0]
    cum_tokens = [tokens_by_phase.get("setup", 0)]
    for i in range(1, n_fires + 1):
        fire_tokens = tokens_by_phase.get(f"fire_{i}", 0) + tokens_by_phase.get(
            f"fire_{i}_review",
            0,
        )
        if operator_fix_before == i:
            fire_tokens += tokens_by_phase.get("operator_fix", 0)
        cum_tokens.append(cum_tokens[-1] + fire_tokens)
        cum_correct.append(
            cum_correct[-1] + (1 if fires.get(i, {}).get("correct") else 0),
        )
    return cum_correct, cum_tokens


def _x(i: int, n: int) -> float:
    plot_w = WIDTH - MARGIN_L - MARGIN_R
    return MARGIN_L + plot_w * (i / n)


def _y(value: float, vmax: float, panel_top: float) -> float:
    vmax = max(vmax, 1)
    return panel_top + PANEL_H - (PANEL_H - 18) * (value / vmax) - 6


def _polyline(xs: list[float], ys: list[float]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))


def _markers(xs: list[float], ys: list[float], color: str, shape: str) -> list[str]:
    out = []
    for x, y in zip(xs, ys):
        if shape == "circle":
            out.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" '
                f'stroke="{SURFACE}" stroke-width="2"/>',
            )
        elif shape == "diamond":
            out.append(
                f'<path d="M {x:.1f} {y - 5:.1f} L {x + 5:.1f} {y:.1f} '
                f'L {x:.1f} {y + 5:.1f} L {x - 5:.1f} {y:.1f} Z" fill="{color}" '
                f'stroke="{SURFACE}" stroke-width="2"/>',
            )
        elif shape == "triangle":
            out.append(
                f'<path d="M {x:.1f} {y - 5:.1f} L {x + 4.5:.1f} {y + 4:.1f} '
                f'L {x - 4.5:.1f} {y + 4:.1f} Z" fill="{color}" '
                f'stroke="{SURFACE}" stroke-width="2"/>',
            )
        else:
            out.append(
                f'<rect x="{x - 4:.1f}" y="{y - 4:.1f}" width="8" height="8" '
                f'fill="{color}" stroke="{SURFACE}" stroke-width="2"/>',
            )
    return out


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _panel(
    *,
    title: str,
    panel_top: float,
    n: int,
    series: list[tuple[list[int], str, str, str]],
    fmt,
    drift_after: int,
    annotations: list[tuple[int, str, str]],
    hermes_unattended: list[int] | None = None,
) -> list[str]:
    vmax = max(max(max(vals) for vals, _, _, _ in series), 1)
    parts = [
        f'<text x="{MARGIN_L}" y="{panel_top - 10}" fill="{INK}" '
        f'font-size="14" font-weight="600">{html.escape(title)}</text>',
    ]
    # Recessive horizontal grid: 4 lines + baseline.
    for frac in (0.25, 0.5, 0.75, 1.0):
        gy = _y(vmax * frac, vmax, panel_top)
        parts.append(
            f'<line x1="{MARGIN_L}" y1="{gy:.1f}" x2="{WIDTH - MARGIN_R}" '
            f'y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>',
        )
        parts.append(
            f'<text x="{MARGIN_L - 8}" y="{gy + 4:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="end">{fmt(round(vmax * frac))}</text>',
        )
    base_y = _y(0, vmax, panel_top)
    parts.append(
        f'<line x1="{MARGIN_L}" y1="{base_y:.1f}" x2="{WIDTH - MARGIN_R}" '
        f'y2="{base_y:.1f}" stroke="{INK_MUTED}" stroke-width="1"/>',
    )
    # Drift rule between fire drift_after and drift_after+1.
    dx = (_x(drift_after, n) + _x(drift_after + 1, n)) / 2
    parts.append(
        f'<line x1="{dx:.1f}" y1="{panel_top - 2}" x2="{dx:.1f}" '
        f'y2="{base_y:.1f}" stroke="{INK_MUTED}" stroke-width="1" '
        f'stroke-dasharray="4 4"/>',
    )
    parts.append(
        f'<text x="{dx + 6:.1f}" y="{panel_top + 10}" fill="{INK_MUTED}" '
        f'font-size="11">API drift</text>',
    )

    xs = [_x(i, n) for i in range(n + 1)]
    if hermes_unattended is not None:
        ys = [_y(v, vmax, panel_top) for v in hermes_unattended]
        parts.append(
            f'<polyline points="{_polyline(xs, ys)}" fill="none" '
            f'stroke="{HERMES_COLOR}" stroke-width="2" stroke-dasharray="5 5" '
            f'opacity="0.75"/>',
        )
    for vals, color, shape, _name in series:
        ys = [_y(v, vmax, panel_top) for v in vals]
        parts.append(
            f'<polyline points="{_polyline(xs, ys)}" fill="none" '
            f'stroke="{color}" stroke-width="2"/>',
        )
        parts.extend(_markers(xs, ys, color, shape))

    # Direct end labels (identity + final value), ink text with color chip.
    label_rows = [(vals, color, name) for vals, color, _shape, name in reversed(series)]
    if hermes_unattended is not None:
        label_rows.append((hermes_unattended, HERMES_COLOR, "hermes alone"))
    used_ys: list[float] = []
    for vals, color, name in label_rows:
        ey = _y(vals[-1], vmax, panel_top)
        while any(abs(ey - u) < 16 for u in used_ys):
            ey += 16
        used_ys.append(ey)
        chip = (
            f'<rect x="{WIDTH - MARGIN_R + 8}" y="{ey - 5:.1f}" width="10" '
            f'height="10" fill="{color}"/>'
            if "alone" not in name
            else f'<line x1="{WIDTH - MARGIN_R + 6}" y1="{ey:.1f}" '
            f'x2="{WIDTH - MARGIN_R + 20}" y2="{ey:.1f}" stroke="{color}" '
            f'stroke-width="2" stroke-dasharray="4 3"/>'
        )
        parts.append(chip)
        parts.append(
            f'<text x="{WIDTH - MARGIN_R + 23}" y="{ey + 4:.1f}" fill="{INK}" '
            f'font-size="12">{html.escape(name)} · {fmt(vals[-1])}</text>',
        )
    for fire_idx, text, anchor in annotations:
        ax = _x(fire_idx, n)
        parts.append(
            f'<text x="{ax:.1f}" y="{base_y + 30:.1f}" fill="{INK_MUTED}" '
            f'font-size="11" text-anchor="{anchor}">{html.escape(text)}</text>',
        )
    return parts


def render(
    unify_results: dict[str, Any],
    hermes_results: dict[str, Any],
    openclaw_results: dict[str, Any] | None = None,
    opencode_results: dict[str, Any] | None = None,
) -> str:
    n = int(unify_results["n_fires"])
    drift_after = int(unify_results["drift_after_fire"])
    u_correct, u_tokens = _series(unify_results)
    h_correct, h_tokens = _series(hermes_results)
    o_correct = o_tokens = None
    if openclaw_results is not None:
        o_correct, o_tokens = _series(openclaw_results)
    c_correct = c_tokens = None
    if opencode_results is not None:
        c_correct, c_tokens = _series(opencode_results)

    height = MARGIN_TOP + PANEL_H + PANEL_GAP + PANEL_H + MARGIN_BOTTOM
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="system-ui, -apple-system, '
        f'Segoe UI, sans-serif">',
        f'<rect width="{WIDTH}" height="{height}" fill="{SURFACE}"/>',
        f'<text x="{MARGIN_L}" y="26" fill="{INK}" font-size="17" font-weight="700">'
        "Same verbal request, same API drift: who keeps delivering, and what it costs"
        "</text>",
        f'<text x="{MARGIN_L}" y="44" fill="{INK_MUTED}" font-size="12">'
        "One natural-language request · gpt-5.6-sol via OpenRouter · dashed = no "
        "human available · API field renamed after fire "
        f"{drift_after}</text>",
    ]

    def _mk_series(correct_or_tokens: str) -> list[tuple[list[int], str, str, str]]:
        rows: list[tuple[list[int], str, str, str]] = [
            (
                h_correct if correct_or_tokens == "correct" else h_tokens,
                HERMES_COLOR,
                "square",
                "hermes + human",
            ),
        ]
        if o_correct is not None:
            rows.append(
                (
                    o_correct if correct_or_tokens == "correct" else o_tokens,
                    OPENCLAW_COLOR,
                    "triangle",
                    "openclaw",
                ),
            )
        if c_correct is not None:
            rows.append(
                (
                    c_correct if correct_or_tokens == "correct" else c_tokens,
                    OPENCODE_COLOR,
                    "diamond",
                    "opencode",
                ),
            )
        rows.append(
            (
                u_correct if correct_or_tokens == "correct" else u_tokens,
                UNIFY_COLOR,
                "circle",
                "Unify",
            ),
        )
        return rows

    hermes_unattended = _series_unattended(hermes_results)
    ha_correct = hermes_unattended[0] if hermes_unattended else None
    ha_tokens = hermes_unattended[1] if hermes_unattended else None
    op_fix = (hermes_results.get("operator_fix") or {}).get("before_fire")
    top_annotations = []
    cost_annotations = [(drift_after + 1, "self-repair", "middle")]
    if op_fix:
        cost_annotations.append((int(op_fix), "human asks hermes to fix it", "middle"))

    parts += _panel(
        title="Reliability — cumulative correct deliveries",
        panel_top=MARGIN_TOP,
        n=n,
        series=_mk_series("correct"),
        fmt=lambda v: str(v),
        drift_after=drift_after,
        annotations=top_annotations,
        hermes_unattended=ha_correct,
    )
    cost_top = MARGIN_TOP + PANEL_H + PANEL_GAP
    parts += _panel(
        title="Cost — cumulative LLM tokens",
        panel_top=cost_top,
        n=n,
        series=_mk_series("tokens"),
        fmt=lambda v: _fmt_tokens(int(v)),
        drift_after=drift_after,
        annotations=cost_annotations,
        hermes_unattended=ha_tokens,
    )
    # Shared x labels under the bottom panel.
    base_y = _y(0, 1, cost_top)
    for i in range(n + 1):
        label = "setup" if i == 0 else str(i)
        parts.append(
            f'<text x="{_x(i, n):.1f}" y="{base_y + 16:.1f}" fill="{INK_MUTED}" '
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
    out = EXPERIMENT_DIR / "results" / "drift_recovery.svg"
    out.write_text(
        render(unify_results, hermes_results, openclaw_results, opencode_results),
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
