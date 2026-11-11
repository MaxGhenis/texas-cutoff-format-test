"""A planning table: what the design can show, under assumed spreads. No answer enters it.

The pooled difference between two arms averages, over 16 evidence files, the mean of the two families'
differences. If answers vary within a cell with standard deviation `sd_cell` (isolated arms), grid
contexts' jumps vary with `sd_grid`, and the true difference varies across files with `sd_files`, its
standard error with r contexts a cell is

    sqrt( ( (S * sd_cell^2 + sd_grid^2) / (2 r) + sd_files^2 ) / 16 ),   S = sum of squared weights = 1.989.

The table gives that standard error, the chance that the equivalence test passes when the arms truly
agree, and the smallest true difference the two-sided test finds four times in five. `sealed_spread`
adds the one piece of data the plan can lean on: how much the sealed runs' own answers varied across
runs, which mixes context noise with differences in research and so bounds `sd_cell` from above.
"""

from __future__ import annotations

import json
import math

import numpy as np
from scipy import stats

from . import design, paths
from .jump import QUESTIONS

SD_CELL = (3.0, 5.0, 8.0, 12.0)  # points
SD_FILES = (0.0, 2.0, 4.0)


def standard_error(sd_cell: float, sd_grid: float, sd_files: float, r: int, n_files: int = design.N_FILES) -> float:
    within = (design.SUM_W2 * sd_cell**2 + sd_grid**2) / (2 * r)
    return math.sqrt((within + sd_files**2) / n_files)


def equivalence_power(se: float, margin: float, n_files: int = design.N_FILES) -> float:
    """The chance both one-sided tests reject at 5% when the true difference is zero (normal
    approximation around the t critical value)."""
    return max(0.0, 2 * stats.norm.cdf(margin / se - stats.t.ppf(0.95, n_files - 1)) - 1)


def detectable(se: float, n_files: int = design.N_FILES) -> float:
    """The true difference a two-sided 5% test finds with 80% power."""
    return (stats.t.ppf(0.975, n_files - 1) + stats.norm.ppf(0.80)) * se


def sealed_spread() -> dict:
    """For each family and question: the standard deviation across the accepted sealed runs of the
    answer at a cell (averaged over the six cells), and of the runs' jumps."""
    ref = json.loads((paths.DESIGN / "reference.json").read_text())
    out: dict = {}
    for fam in design.FAMILIES:
        runs = [r for r in ref["runs"].values() if r["family"] == fam]
        out[fam] = {}
        for q in QUESTIONS:
            cells = np.array([r["questions"][q]["cells"] for r in runs])
            jumps = np.array([r["questions"][q]["jump"] for r in runs])
            out[fam][q] = {"sd_cell": float(cells.std(axis=0, ddof=1).mean()), "sd_jump": float(jumps.std(ddof=1))}
    return out


def table() -> str:
    margin = design.MARGIN["ercot_pause_lifted"]
    lines = [
        "# Planning table",
        "",
        "Assumed spreads, not results: no context's answer enters this table.",
        "",
        f"Margin {margin:g} points; 16 evidence files; grid jumps assumed to vary as much as "
        "sqrt(S) times the within-cell spread (as if a grid context's six answers varied independently).",
        "",
        "| Spread within a cell (points) | Spread of the true difference across files | Contexts a cell | Standard error | "
        "Chance equivalence shows if the arms agree | Smallest difference found 4 times in 5 |",
        "|---|---|---|---|---|---|",
    ]
    for sd_cell in SD_CELL:
        for sd_files in SD_FILES:
            for r in (design.R_BASE, design.R_MAX):
                se = standard_error(sd_cell, math.sqrt(design.SUM_W2) * sd_cell, sd_files, r)
                lines.append(
                    f"| {sd_cell:g} | {sd_files:g} | {r} | {se:.2f} | {equivalence_power(se, margin):.2f} | {detectable(se):.1f} |"
                )
    lines += [
        "",
        f"The registered rule asks for a standard error of at most {design.required_se('ercot_pause_lifted'):.2f} points "
        "(an 80% chance that equivalence shows when the arms agree), from within-file noise alone. More contexts "
        "cannot shrink the spread of the true difference across files.",
        "",
        "## What the sealed runs suggest",
        "",
        "Spread across each family's six accepted sealed runs. It mixes context noise with differences in research, "
        "so it bounds the within-cell spread from above. Model forecasts, not observations.",
        "",
        "| Family | Question | Spread of an answer at a cell | Spread of the jump |",
        "|---|---|---|---|",
    ]
    for fam, by_q in sealed_spread().items():
        for q, s in by_q.items():
            lines.append(f"| {fam} | `{q}` | {s['sd_cell']:.2f} | {s['sd_jump']:.2f} |")
    t_margin = design.MARGIN["senate_dem_share"]
    lines += [
        "",
        "## Talarico's share",
        "",
        f"The margin is {t_margin:g} points. Equivalence can show only if the 90% interval's half-width, "
        f"{stats.t.ppf(0.95, design.N_FILES - 1):.2f} standard errors, stays under it: a standard error below "
        f"{t_margin / stats.t.ppf(0.95, design.N_FILES - 1):.3f} points. With six contexts a cell and no spread across "
        "files, that needs a within-cell spread below "
        f"{t_margin / stats.t.ppf(0.95, design.N_FILES - 1) * math.sqrt(16 * 2 * 6 / (2 * design.SUM_W2)):.2f} points. "
        "The registration treats Talarico's share as a secondary result for that reason.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    paths.OUTPUTS.mkdir(exist_ok=True)
    (paths.OUTPUTS / "power.md").write_text(table())
    print(table())
    return 0
