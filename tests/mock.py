"""MOCK answers for tests: numbers a known process makes up. Nothing here comes from a model."""

from __future__ import annotations

import numpy as np

from cutoff import design, sources
from cutoff.jump import CELLS, KEYS, QUESTIONS, SCALE

BASE = {"ercot_pause_lifted": 70.0, "special_session_data_centers": 30.0, "senate_dem_share": 49.0}
SLOPE = {"ercot_pause_lifted": -1.0, "special_session_data_centers": 0.8, "senate_dem_share": 0.95}
# MOCK truth: the raw jump each family draws in the grid arm.
GRID_JUMP = {
    "opus": {"ercot_pause_lifted": -20.0, "special_session_data_centers": 14.0, "senate_dem_share": 0.0},
    "sol": {"ercot_pause_lifted": -8.0, "special_session_data_centers": 18.0, "senate_dem_share": 0.0},
}


def mock_rows(format_effect=None, sd=0.0, replicates=3, seed=0, labels=sources.LABELS, families=design.FAMILIES):
    """MOCK rows shaped like outputs/answers.csv (values in points). `format_effect[arm][question]`
    is added to the raw jump in that arm (default 0 everywhere); `sd` is the spread of the noise added
    to each answer."""
    rng = np.random.default_rng(seed)
    format_effect = format_effect or {}
    rows = []
    for f in labels:
        for m in families:
            for arm in ("grid", "alone", "told"):
                for k in range(1, replicates + 1):
                    contexts = [None] if arm == "grid" else list(CELLS)
                    for own in contexts:
                        cid = f"{f}.{m}.{arm}.{'all' if own is None else 'dem_%.1f' % own}.r{k}"
                        for q in QUESTIONS:
                            j = GRID_JUMP[m][q] + format_effect.get(arm, {}).get(q, 0.0)
                            for c, key in zip(CELLS, KEYS):
                                if own is not None and c != own:
                                    continue
                                value = BASE[q] + SLOPE[q] * (c - 50.0) + (j if c > 50 else 0.0) + rng.normal(0, sd)
                                rows.append(
                                    {
                                        "context": cid, "file": f, "source_family": sources.family(f), "family": m,
                                        "arm": arm, "cell": "all" if own is None else key, "replicate": k,
                                        "wave": 1 if f in design.first_batch_files() else 2, "attempt": 1,
                                        "question": q, "key": key, "value": float(value), "repaired": "0",
                                        "prior_read": "0", "canary": "0", "job_id": "MOCK",
                                    }
                                )  # fmt: skip
    return rows


def mock_reference(offset=0.0):
    """A MOCK design/reference.json: each accepted run's sealed jump is the MOCK grid jump of its
    family minus `offset` (so a closed grid jump exceeds it by `offset`)."""
    runs = {}
    for label in sources.ACCEPTED:
        fam = sources.family(label)
        runs[label] = {
            "family": fam,
            "questions": {q: {"jump": GRID_JUMP[fam][q] - offset, "cells": [0.0] * 6} for q in QUESTIONS},
        }
    return {"runs": runs}
