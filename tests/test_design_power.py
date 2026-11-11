"""The registered design (which contexts run, in what order, under which ids) and the replicate rule."""

from __future__ import annotations

import csv
import math
import uuid
from collections import Counter

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from mock import mock_rows
from scipy import stats

from cutoff import analysis, design, dispatch, paths, power, prompts, sources
from cutoff.jump import CELLS, KEYS

ROWS = design.context_rows()


def test_the_design_dispatches_2496_contexts_1248_of_them_at_three_replicates():
    assert len(ROWS) == 2496
    assert sum(r["replicate"] <= design.R_BASE for r in ROWS) == 1248
    assert Counter(r["wave"] for r in ROWS) == {1: 156, 2: 1092, 3: 1248}


def test_each_file_and_family_gets_3_grid_and_18_contexts_in_each_isolated_arm():
    base = [r for r in ROWS if r["replicate"] <= design.R_BASE]
    by = Counter((r["file"], r["family"], r["arm"]) for r in base)
    assert set(by) == {(f, m, a) for f in sources.LABELS for m in design.FAMILIES for a in prompts.ARMS}
    for (f, m, arm), n in by.items():
        assert n == (3 if arm == "grid" else 18)
    for r in base:
        assert (r["cell"] == "all") == (r["arm"] == "grid")
        assert r["cell"] == "all" or r["cell"] in KEYS


def test_ids_names_and_request_ids_are_unique_and_follow_the_registered_forms():
    assert len({r["context"] for r in ROWS}) == len(ROWS)
    assert [r["order"] for r in ROWS] == list(range(1, len(ROWS) + 1))
    assert [r["name"] for r in ROWS] == [f"tcf-{k:04d}" for k in range(1, len(ROWS) + 1)]
    for r in ROWS:
        assert r["context"] == f"{r['file']}.{r['family']}.{r['arm']}.{r['cell']}.r{r['replicate']}"
        assert r["request_id"] == str(uuid.uuid5(design.NAMESPACE, r["context"]))
        assert dispatch.request_id(r["context"], 1) == r["request_id"]
        assert r["source_family"] == sources.family(r["file"])
    assert len({dispatch.request_id(r["context"], a) for r in ROWS[:50] for a in (1, 2, 3)}) == 150


def test_waves_run_in_order_and_the_first_batch_is_one_accepted_opus_file_and_one_sol_file():
    waves = [r["wave"] for r in ROWS]
    assert waves == sorted(waves)
    opus, sol = design.first_batch_files()
    assert opus in sources.ACCEPTED and sources.family(opus) == "opus"
    assert sol in sources.SOL
    assert {r["file"] for r in ROWS if r["wave"] == 1} == {opus, sol}
    assert all(r["wave"] == 3 for r in ROWS if r["replicate"] > design.R_BASE)
    assert design.first_batch_files() == design.first_batch_files(design.SEED)


def test_each_context_names_a_registered_prompt():
    ids = {prompts.prompt_id(f, a, c) for f in sources.LABELS for a, c in prompts.variants()}
    assert {r["prompt"] for r in ROWS} == ids
    table = paths.DESIGN / "prompts.csv"
    if table.exists():
        with table.open() as fh:
            assert {r["prompt"] for r in csv.DictReader(fh)} == ids


def test_the_committed_contexts_table_is_the_designs():
    table = paths.DESIGN / "contexts.csv"
    if not table.exists():
        pytest.skip("design/contexts.csv is not built")
    with table.open() as fh:
        committed = list(csv.DictReader(fh))
    assert committed == [{k: str(v) for k, v in r.items()} for r in ROWS]


# ------------------------------------------------------------------------------- the replicate rule


def test_the_required_standard_error_is_the_margin_over_t_plus_z():
    for q in design.PRIMARY:
        want = design.MARGIN[q] / (stats.t.ppf(0.95, 15) + stats.norm.ppf(0.90))
        assert design.required_se(q) == pytest.approx(want)
    assert design.required_se("ercot_pause_lifted") == pytest.approx(1.65, abs=0.005)


variance = st.floats(0.0, 400.0, allow_nan=False)
spreads = st.fixed_dictionaries({m: variance for m in design.FAMILIES})


@settings(max_examples=200, deadline=None)
@given(spreads, spreads, st.integers(1, 12))
def test_projected_se_falls_as_one_over_root_r(cell, grid, r):
    se1 = design.projected_se(cell, grid, 1)
    assert design.projected_se(cell, grid, r) == pytest.approx(se1 / math.sqrt(r))


@settings(max_examples=300, deadline=None)
@given(st.fixed_dictionaries({q: st.fixed_dictionaries({"cell": spreads, "grid": spreads}) for q in design.PRIMARY}))
def test_the_rule_picks_the_smallest_r_that_meets_the_target_on_both_primaries(spread):
    def meets(r):
        return all(design.projected_se(spread[q]["cell"], spread[q]["grid"], r) <= design.required_se(q) for q in design.PRIMARY)

    r = design.replicates_rule(spread)
    assert design.R_BASE <= r <= design.R_MAX
    if meets(r):
        assert all(not meets(k) for k in range(design.R_BASE, r))
    else:
        assert r == design.R_MAX and not any(meets(k) for k in range(design.R_BASE, design.R_MAX + 1))


def test_projected_se_matches_the_spread_of_the_pooled_estimate_in_simulation():
    """Differential: the formula against the analysis run on MOCK answers with known noise."""
    sd, r = 4.0, 3
    q = "ercot_pause_lifted"
    estimates = []
    for seed in range(40):
        rows = mock_rows(sd=sd, replicates=r, seed=seed)
        sj = analysis.signed_jumps(analysis.jumps(rows))
        d = analysis.file_differences(sj, q, "alone", "grid", design.FAMILIES)
        estimates.append(np.mean(list(d.values())))
    s2 = {m: sd**2 for m in design.FAMILIES}
    grid = {m: design.SUM_W2 * sd**2 for m in design.FAMILIES}  # a grid context's jump: six noisy answers
    want = design.projected_se(s2, grid, r)
    assert np.std(estimates, ddof=1) == pytest.approx(want, rel=0.3)


def test_first_batch_spread_recovers_the_noise_it_was_made_with():
    sd = 5.0
    opus, sol = design.first_batch_files()
    rows = mock_rows(sd=sd, replicates=3, seed=7, labels=(opus, sol))
    spread = analysis.first_batch_spread(rows)
    for q in design.PRIMARY:
        for m in design.FAMILIES:
            assert spread[q]["cell"][m] == pytest.approx(sd**2, rel=0.6)
    assert design.replicates_rule(spread) in range(design.R_BASE, design.R_MAX + 1)


# ------------------------------------------------------------------------------------------ power


@settings(max_examples=200, deadline=None)
@given(st.floats(0.1, 20), st.floats(0.0, 20), st.floats(0.0, 10), st.integers(1, 6))
def test_standard_error_falls_with_replicates_and_rises_with_noise(sd_cell, sd_grid, sd_files, r):
    se = power.standard_error(sd_cell, sd_grid, sd_files, r)
    assert se >= power.standard_error(sd_cell, sd_grid, sd_files, r + 1)
    assert se <= power.standard_error(sd_cell + 1, sd_grid, sd_files, r)


@settings(max_examples=200, deadline=None)
@given(st.floats(0.05, 20), st.floats(0.05, 20))
def test_equivalence_power_is_a_probability_that_falls_as_the_standard_error_rises(a, b):
    lo, hi = sorted((a, b))
    p_lo, p_hi = power.equivalence_power(lo, 5.0), power.equivalence_power(hi, 5.0)
    assert 0.0 <= p_hi <= p_lo <= 1.0
    assert power.detectable(lo) <= power.detectable(hi)


def test_power_table_matches_the_committed_one():
    committed = paths.ROOT / "outputs" / "power.md"
    if not committed.exists():
        pytest.skip("outputs/power.md is not written")
    assert committed.read_text() == power.table()


def test_cells_are_the_registered_six():
    assert CELLS == (44.0, 47.0, 49.5, 50.5, 53.0, 56.0)
