"""SVG digests for fire-series runs — outcomes per fire, tokens per fire by purpose.

Stdlib only, like every plot in this repo, so a third party can regenerate
the figures from the committed ``results/`` without installing anything.

Two readers are shared with ``plot_distillation_curve``:

``latest_runs``   newest ``results.json`` per arm under an experiment's
                  ``results/`` (optionally per variant);
``fire_series``   per-fire rows of ``(fire, outcome, tokens-by-purpose)``
                  from a run record, deriving tokens from the phase table
                  when the record predates ``fires[i].tokens``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from colleague.tracks.standing.series.report import PURPOSES, attach_fire_tokens
from colleague.tracks.standing.series.spec import Experiment

#: Person-shaped arms first; the retired old-regime arm names stay so the
#: committed runs they produced keep plotting, clearly apart from reruns.
ARM_ORDER = (
    "unify-cm",
    "hermes-tui",
    "openclaw-gateway",
    "opencode",
    "prime-agent-rpc",
    "unify",
    "hermes",
    "openclaw",
    "prime-agent",
)
ARM_COLOR = {
    "unify-cm": "#1b5fb8",
    "hermes-tui": "#c94f1c",
    "openclaw-gateway": "#00785a",
    "prime-agent-rpc": "#a85b8c",
    "unify": "#2a78d6",
    "hermes": "#eb6834",
    "openclaw": "#009E73",
    "opencode": "#7B52AB",
    "prime-agent": "#CC79A7",
}
PURPOSE_SHADE = {"planning": 1.0, "verification": 0.55, "repair": 0.25}
OUTCOME_COLOR = {"correct": "#2e9e5b", "held": "#e0a100", "wrong": "#d0342c"}
SURFACE = "#fcfcfb"
INK = "#1a1a19"
INK_MUTED = "#6f6e6a"
GRID = "#e8e7e4"

_FIRE_PHASE = re.compile(r"^(?:fire|run|week)_(\d+)$")


_ARM_ALIASES = {"hermes-agent": "hermes"}


def _run_arm(run_dir: Path, data: dict[str, Any]) -> str | None:
    """Which arm a run belongs to: its ``system`` field, else its directory suffix.

    The first `recurring_report` unify runs predate both the field and the
    suffix; a run with neither is unify's, since no other arm ever wrote one.
    """
    system = data.get("system")
    if system:
        return _ARM_ALIASES.get(str(system), str(system))
    suffix = run_dir.name.rsplit("-", 1)[-1]
    return suffix if suffix in ARM_ORDER else "unify"


def latest_runs(
    experiment_dir: Path,
    *,
    variant: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Newest run record per arm. With ``variant``, only runs of that variant."""
    out: dict[str, dict[str, Any]] = {}
    results = experiment_dir / "results"
    if not results.is_dir():
        return out
    for run_dir in sorted(results.iterdir()):
        path = run_dir / "results.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        arm = _run_arm(run_dir, data)
        if arm not in ARM_ORDER:
            continue
        if variant is not None and data.get("variant") != variant:
            continue
        if variant is None and data.get("variant"):
            continue
        out[arm] = data
    return out


class _Labeller(Experiment):
    """Just enough of an experiment to name a run's fire phases."""

    def __init__(self, noun: str) -> None:
        self.fire_noun = noun


def fire_series(results: dict[str, Any]) -> list[dict[str, Any]]:
    """``[{fire, outcome, tokens}]`` for a run, oldest record formats included.

    Tokens are always re-derived from the phase table (with the owner-message
    and operator-fix phases folded into the fire they preceded), so records
    written before ``fires[i].tokens`` existed and records written since read
    the same way.
    """
    phases = results.get("phases") or []
    names = {str(p.get("name")) for p in phases}
    fires = results.get("fires") or results.get("runs") or []
    rows = []
    for row in fires:
        i = int(row.get("fire") or row.get("run") or row.get("week") or 0)
        if not i:
            continue
        outcome = (
            row["outcome"]
            if "outcome" in row
            else ("correct" if row.get("correct") else "wrong")
        )
        rows.append({"fire": i, "outcome": outcome, "tokens": row.get("tokens") or {}})
    noun = next(
        (
            n
            for n in ("fire", "run", "week")
            if any(f"{n}_{r['fire']}" in names for r in rows)
        ),
        "fire",
    )
    fix = results.get("operator_fix")
    if phases:
        attach_fire_tokens(
            rows,
            phases,
            _Labeller(noun),
            operator_fix_before=(
                int(fix["before_fire"])
                if isinstance(fix, dict) and fix.get("before_fire")
                else None
            ),
        )
    return sorted(rows, key=lambda r: r["fire"])


def n_fires(results: dict[str, Any]) -> int:
    return int(
        results.get("n_fires") or results.get("n_runs") or len(fire_series(results)),
    )


def _shade(hex_color: str, factor: float) -> str:
    """Blend a colour towards white; ``factor`` 1.0 is the colour itself."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    r = int(r + (255 - r) * (1 - factor))
    g = int(g + (255 - g) * (1 - factor))
    b = int(b + (255 - b) * (1 - factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_experiment(
    experiment_dir: Path,
    *,
    title: str,
    subtitle: str = "",
    variant: str | None = None,
    events: dict[int, str] | None = None,
    out_path: Path | None = None,
) -> Path | None:
    """One SVG: outcome strip per arm on top, tokens per fire by purpose below."""
    runs = latest_runs(experiment_dir, variant=variant)
    if not runs:
        print(
            f"[plot] no runs under {experiment_dir / 'results'}"
            + (f" for variant {variant}" if variant else ""),
        )
        return None
    arms = [a for a in ARM_ORDER if a in runs]
    series = {a: fire_series(runs[a]) for a in arms}
    total_fires = max(n_fires(runs[a]) for a in arms)
    width = 900
    margin_l, margin_r, top = 110, 40, 70
    strip_h = 22
    strip_top = top
    bars_top = strip_top + strip_h * len(arms) + 50
    bars_h = 220
    height = bars_top + bars_h + 70
    plot_w = width - margin_l - margin_r
    slot = plot_w / total_fires
    bar_w = max(4.0, (slot - 8) / max(1, len(arms)))
    max_tokens = max(
        [1] + [int(r["tokens"].get("total", 0)) for a in arms for r in series[a]],
    )

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="Inter, Helvetica, Arial, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
        f'<text x="{margin_l}" y="30" font-size="17" font-weight="600" fill="{INK}">{_esc(title)}</text>',
        f'<text x="{margin_l}" y="50" font-size="12" fill="{INK_MUTED}">{_esc(subtitle)}</text>',
    ]
    # Outcome strips.
    for k, arm in enumerate(arms):
        y = strip_top + k * strip_h + strip_h / 2
        svg.append(
            f'<text x="{margin_l - 10}" y="{y + 4}" font-size="12" text-anchor="end" fill="{ARM_COLOR[arm]}" font-weight="600">{arm}</text>',
        )
        by_fire = {r["fire"]: r for r in series[arm]}
        for i in range(1, total_fires + 1):
            cx = margin_l + slot * (i - 0.5)
            row = by_fire.get(i)
            if row is None:
                svg.append(
                    f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="5" fill="none" stroke="{GRID}"/>',
                )
                continue
            color = OUTCOME_COLOR.get(row["outcome"], INK_MUTED)
            if row["outcome"] == "held":
                svg.append(
                    f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="6" fill="{SURFACE}" stroke="{color}" stroke-width="2"/>',
                )
                svg.append(
                    f'<path d="M {cx:.1f} {y - 6:.1f} A 6 6 0 0 1 {cx:.1f} {y + 6:.1f} Z" fill="{color}"/>',
                )
            elif row["outcome"] == "correct":
                svg.append(f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>')
            else:
                svg.append(
                    f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="6" fill="none" stroke="{color}" stroke-width="2"/>',
                )
                svg.append(
                    f'<line x1="{cx - 4:.1f}" y1="{y - 4:.1f}" x2="{cx + 4:.1f}" y2="{y + 4:.1f}" stroke="{color}" stroke-width="2"/>',
                )
    legend_y = strip_top + strip_h * len(arms) + 18
    svg.append(
        f'<text x="{margin_l}" y="{legend_y}" font-size="11" fill="{INK_MUTED}">● correct (2)   ◐ held with reason (1)   ⊘ wrong or silent (0)</text>',
    )

    # Token bars.
    axis_bottom = bars_top + bars_h
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = axis_bottom - bars_h * frac
        svg.append(
            f'<line x1="{margin_l}" y1="{y:.1f}" x2="{width - margin_r}" y2="{y:.1f}" stroke="{GRID}"/>',
        )
        svg.append(
            f'<text x="{margin_l - 8}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="{INK_MUTED}">{int(max_tokens * frac):,}</text>',
        )
    svg.append(
        f'<text x="{margin_l - 90}" y="{bars_top - 12}" font-size="11" fill="{INK_MUTED}">LLM tokens per fire</text>',
    )
    for i in range(1, total_fires + 1):
        x0 = margin_l + slot * (i - 1) + 4
        svg.append(
            f'<text x="{margin_l + slot * (i - 0.5):.1f}" y="{axis_bottom + 16}" font-size="11" text-anchor="middle" fill="{INK}">{i}</text>',
        )
        for k, arm in enumerate(arms):
            row = next((r for r in series[arm] if r["fire"] == i), None)
            if row is None:
                continue
            x = x0 + k * bar_w
            y = axis_bottom
            for purpose in PURPOSES:
                bucket = row["tokens"].get(purpose) or {}
                amount = int(bucket.get("prompt", 0)) + int(bucket.get("completion", 0))
                if amount <= 0:
                    continue
                h = bars_h * amount / max_tokens
                y -= h
                svg.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 1:.1f}" height="{h:.1f}" fill="{_shade(ARM_COLOR[arm], PURPOSE_SHADE[purpose])}"><title>{arm} fire {i} {purpose}: {amount:,}</title></rect>',
                )
    # Events (drift, change) as vertical markers.
    for fire, label in sorted((events or {}).items()):
        x = margin_l + slot * (fire - 1)
        svg.append(
            f'<line x1="{x:.1f}" y1="{strip_top - 8}" x2="{x:.1f}" y2="{axis_bottom}" stroke="{INK_MUTED}" stroke-dasharray="4 3"/>',
        )
        svg.append(
            f'<text x="{x + 4:.1f}" y="{strip_top - 12}" font-size="10" fill="{INK_MUTED}">{_esc(label)}</text>',
        )
    # Legend for shades.
    ly = axis_bottom + 40
    lx = margin_l
    for arm in arms:
        svg.append(
            f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{ARM_COLOR[arm]}"/>',
        )
        svg.append(
            f'<text x="{lx + 16}" y="{ly}" font-size="11" fill="{INK}">{arm}</text>',
        )
        lx += 20 + 8 * len(arm) + 16
    lx += 20
    for purpose in PURPOSES:
        svg.append(
            f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{_shade(ARM_COLOR["unify-cm"], PURPOSE_SHADE[purpose])}"/>',
        )
        svg.append(
            f'<text x="{lx + 16}" y="{ly}" font-size="11" fill="{INK}">{purpose}</text>',
        )
        lx += 20 + 8 * len(purpose) + 16
    svg.append(
        f'<text x="{margin_l}" y="{ly + 18}" font-size="10" fill="{INK_MUTED}">Shades split unify tokens by purpose; proxy-metered arms report every token as planning.</text>',
    )
    svg.append("</svg>")

    out = out_path or experiment_dir / (
        f"{experiment_dir.name}" + (f"_{variant}" if variant else "") + ".svg"
    )
    out.write_text("\n".join(svg), encoding="utf-8")
    print(f"[plot] wrote {out}")
    return out
