"""The registered design: which contexts run, in what order, and the rule that sets the replicates.

Each evidence file (16) and answering family (Opus 5.5, GPT-6.1 Sol) gets r contexts per cell in each
arm: r grid contexts, each answering all six cells, and r contexts for each cell in each isolated arm.
At the base r = 3 that is 3 + 18 + 18 = 39 contexts a file and family, 1,248 in all.

- **Wave 1, the first batch:** two files drawn by the seed, one from an accepted Opus run and one from
  a Sol run, both families, every arm, replicates 1-3: 156 contexts.
- **Wave 2:** the other fourteen files, replicates 1-3: 1,092 contexts.
- **Wave 3:** replicates 4-6 for every file, dispatched only up to the r that `replicates_rule`
  picks from wave 1's spread (design/replicates.json records it before wave 3 starts).

Within each wave the dispatch order is a seeded shuffle, so arms, cells and families interleave in
time.
"""

from __future__ import annotations

import math
import uuid

import numpy as np
from scipy import stats

from . import sources
from .jump import CELLS, WEIGHTS
from .prompts import ARMS, cell_key, prompt_id

SEED = 20261110
FAMILIES = ("opus", "sol")
PIN = {"opus": "opus", "sol": "sol61"}  # Subfleet policy aliases: claude-opus-5-5; gpt-6.1-sol at ultra
MODEL = {"opus": "claude-opus-5-5", "sol": "gpt-6.1-sol"}
R_BASE, R_MAX = 3, 6
MARGIN = {"ercot_pause_lifted": 5.0, "special_session_data_centers": 5.0, "senate_dem_share": 0.1}
PRIMARY = ("ercot_pause_lifted", "special_session_data_centers")
N_FILES = len(sources.LABELS)
NAMESPACE = uuid.UUID("6f6a3a52-6d0b-4c1e-9a43-2a3cb1d6c0de")


def first_batch_files(seed: int = SEED) -> tuple[str, str]:
    rng = np.random.default_rng(seed)
    opus = [x for x in sources.ACCEPTED if sources.family(x) == "opus"]
    return str(rng.choice(opus)), str(rng.choice(list(sources.SOL)))


def context_rows(seed: int = SEED) -> list[dict]:
    first = set(first_batch_files(seed))
    rows = []
    for f in sources.LABELS:
        for fam in FAMILIES:
            for arm in ARMS:
                cells = [None] if arm == "grid" else list(CELLS)
                for c in cells:
                    for k in range(1, R_MAX + 1):
                        wave = 3 if k > R_BASE else (1 if f in first else 2)
                        cid = f"{f}.{fam}.{arm}.{'all' if c is None else cell_key(c)}.r{k}"
                        rows.append(
                            {
                                "context": cid,
                                "file": f,
                                "source_family": sources.family(f),
                                "family": fam,
                                "arm": arm,
                                "cell": "all" if c is None else cell_key(c),
                                "replicate": k,
                                "prompt": prompt_id(f, arm, c),
                                "wave": wave,
                                "request_id": str(uuid.uuid5(NAMESPACE, cid)),
                            }
                        )
    rng = np.random.default_rng(seed + 1)
    ordered = []
    for wave in (1, 2, 3):
        block = sorted((r for r in rows if r["wave"] == wave), key=lambda r: r["context"])
        perm = rng.permutation(len(block))
        ordered += [block[i] for i in perm]
    for rank, r in enumerate(ordered, 1):
        r["order"] = rank
        r["name"] = f"tcf-{rank:04d}"
    return ordered


SUM_W2 = float(np.sum(WEIGHTS**2))  # the jump's variance per unit of within-cell variance, one context a cell


def projected_se(sigma2_cell: dict, sigma2_grid: dict, r: int, n_files: int = N_FILES) -> float:
    """The standard error of the pooled primary (the per-file mean of the two families' alone-minus-grid
    differences, averaged over files) if answers vary only within cells: each family's difference has
    variance (SUM_W2 * sigma2_cell + sigma2_grid) / r."""
    var_file = sum((SUM_W2 * sigma2_cell[m] + sigma2_grid[m]) / r for m in FAMILIES) / 4.0
    return math.sqrt(var_file / n_files)


def required_se(question: str, n_files: int = N_FILES) -> float:
    """The largest standard error at which the equivalence test has about an 80% chance of passing when
    the arms truly agree: margin / (t_0.95 with n_files - 1 df + z_0.90)."""
    return MARGIN[question] / (stats.t.ppf(0.95, n_files - 1) + stats.norm.ppf(0.90))


def replicates_rule(spread: dict) -> int:
    """The registered rule: the smallest r in 3..6 at which both primaries' projected standard error
    meets `required_se`, or 6. `spread[question]` holds {"cell": {family: variance}, "grid": {family:
    variance}} from wave 1 (`analysis.first_batch_spread`)."""
    for r in range(R_BASE, R_MAX + 1):
        if all(projected_se(spread[q]["cell"], spread[q]["grid"], r) <= required_se(q) for q in PRIMARY):
            return r
    return R_MAX
