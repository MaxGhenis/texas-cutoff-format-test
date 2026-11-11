"""The registered analysis on MOCK answers made by a known process: it finds effects planted in the
answers, finds none where none were planted, and applies the bridge, Holm's method and the abstract
rule as registered."""

from __future__ import annotations

import csv
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from mock import GRID_JUMP, mock_reference, mock_rows

from cutoff import analysis as A
from cutoff import collect, design, paths
from cutoff.jump import DIRECTION, KEYS, QUESTIONS, jump

ERCOT, SPECIAL = design.PRIMARY


def run(effect=None, sd=1.0, offset=0.0, seed=0, reference=None):
    return A.analyze(mock_rows(effect, sd=sd, seed=seed), reference or mock_reference(offset))


# ---------------------------------------------------------------------------------------------- holm


@settings(max_examples=300, deadline=None)
@given(st.lists(st.floats(0.0, 1.0, allow_nan=False), min_size=1, max_size=6))
def test_holm_raises_each_p_value_keeps_their_order_and_stays_a_probability(ps):
    adj = A.holm(ps)
    assert all(p <= a <= 1.0 for p, a in zip(ps, adj))
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    assert [adj[i] for i in order] == sorted(adj[i] for i in order)


def test_holm_by_hand():
    assert A.holm([0.01, 0.04]) == pytest.approx([0.02, 0.04])
    assert A.holm([0.03, 0.02]) == pytest.approx([0.04, 0.04])
    assert A.holm([0.2]) == [0.2]


# -------------------------------------------------------------------------------------- paired tests


@settings(max_examples=300, deadline=None)
@given(st.lists(st.floats(-20, 20, allow_nan=False), min_size=2, max_size=20), st.floats(0.5, 10))
def test_the_equivalence_test_passes_exactly_when_the_90_interval_lies_inside_the_margin(values, margin):
    rec = A.paired(values, margin)
    if rec["se"] == 0 or rec["se"] < 1e-9 * max(1.0, abs(rec["mean"])):
        return
    lo, hi = rec["ci90"]
    if min(abs(lo + margin), abs(hi - margin)) < 1e-9:
        return  # on the boundary
    assert (rec["p_equivalent"] < 0.05) == rec["equivalent"] == (-margin < lo and hi < margin)


def test_paired_with_fewer_than_two_values_gives_only_the_mean():
    assert A.paired([], 5.0) == {"n": 0, "mean": None}
    assert A.paired([3.0], 5.0) == {"n": 1, "mean": 3.0}


# --------------------------------------------------------------------------------------------- jumps


def test_the_grid_jump_of_cell_means_is_the_mean_of_the_contexts_jumps():
    rows = [r for r in mock_rows(sd=3.0, seed=4) if r["arm"] == "grid"]
    js = A.jumps(rows)
    by_context = {}
    for r in rows:
        by_context.setdefault((r["file"], r["family"], r["question"], r["context"]), {})[r["key"]] = r["value"]
    for (f, m, q), j in [((k[0], k[1], k[3]), v) for k, v in js.items()]:
        own = [jump([c[k] for k in KEYS]) for (ff, mm, qq, _), c in by_context.items() if (ff, mm, qq) == (f, m, q)]
        assert j == pytest.approx(np.mean(own))


def test_a_combination_with_an_empty_cell_has_no_jump():
    rows = [r for r in mock_rows() if not (r["file"] == "opus-1" and r["arm"] == "alone" and r["key"] == "dem_44.0")]
    js = A.jumps(rows)
    assert ("opus-1", "opus", "alone", ERCOT) not in js and ("opus-1", "opus", "told", ERCOT) in js


# -------------------------------------------------------------------------------------- the analysis


def test_with_no_effect_the_arms_agree_and_the_abstract_gives_the_grid_alone():
    res = run(sd=1.0)
    for q in design.PRIMARY:
        d = res["pooled"][q]["differences"]["alone-grid"]
        assert abs(d["mean"]) < 1 and d["verdict"] == "equivalent"
        assert res["pooled"][q]["families"] == list(design.FAMILIES)
    assert res["abstract"]["grid_alone_suffices"]


def test_a_planted_effect_is_found_with_its_sign_and_size():
    res = run({"alone": {ERCOT: 8.0}}, sd=1.0)
    d = res["pooled"][ERCOT]["differences"]["alone-grid"]
    assert d["mean"] == pytest.approx(8.0 * DIRECTION[ERCOT], abs=0.5)
    assert d["verdict"] == "different"
    assert res["pooled"][SPECIAL]["differences"]["alone-grid"]["verdict"] == "equivalent"
    assert res["pooled"][ERCOT]["differences"]["told-grid"]["equivalent"]
    assert res["abstract"]["gives_both_numbers"]
    assert res["abstract"]["checks"] == {f"{ERCOT}:alone-grid": False, f"{ERCOT}:told-grid": True,
                                         f"{SPECIAL}:alone-grid": True, f"{SPECIAL}:told-grid": True}  # fmt: skip


def test_an_effect_in_the_told_arm_alone_still_gives_both_numbers():
    res = run({"told": {SPECIAL: -9.0}}, sd=1.0)
    assert res["pooled"][SPECIAL]["differences"]["told-grid"]["mean"] == pytest.approx(-9.0, abs=0.5)
    assert res["abstract"]["gives_both_numbers"]


def test_the_abstract_keeps_the_alone_number_while_a_holm_verdict_is_unresolved():
    """Both alone-minus-grid intervals sit inside the margin (p = 0.04 each), but Holm doubles the
    p-values, so both verdicts read unresolved and the abstract must give both numbers."""
    rec = {"equivalent": True, "p_equivalent": 0.04, "p_equivalent_holm": 0.08, "verdict": "unresolved"}
    told = {"equivalent": True}
    pooled = {q: {"differences": {"alone-grid": dict(rec), "told-grid": dict(told)}} for q in design.PRIMARY}
    out = A.abstract_rule(pooled)
    assert out["gives_both_numbers"] and not out["grid_alone_suffices"]
    for q in design.PRIMARY:
        pooled[q]["differences"]["alone-grid"]["verdict"] = "equivalent"
    assert A.abstract_rule(pooled)["grid_alone_suffices"]
    pooled[ERCOT]["differences"]["told-grid"]["equivalent"] = False
    assert A.abstract_rule(pooled)["gives_both_numbers"]


def test_a_difference_inside_the_margin_but_not_zero_reads_equivalent():
    res = run({"alone": {ERCOT: 2.0}}, sd=0.5)
    d = res["pooled"][ERCOT]["differences"]["alone-grid"]
    assert d["p_zero_holm"] < 0.05 and d["p_equivalent_holm"] < 0.05
    assert d["verdict"] == "equivalent"


@settings(max_examples=60, deadline=None)
@given(st.floats(-12, 12), st.floats(0.2, 30), st.integers(0, 10_000))
def test_the_abstract_drops_the_alone_number_only_when_every_check_passes(effect, sd, seed):
    res = run({"alone": {ERCOT: effect}}, sd=sd, seed=seed)
    ab = res["abstract"]
    assert ab["grid_alone_suffices"] != ab["gives_both_numbers"]
    if ab["grid_alone_suffices"]:
        for q in design.PRIMARY:
            assert res["pooled"][q]["differences"]["alone-grid"]["verdict"] == "equivalent"
            lo, hi = res["pooled"][q]["differences"]["told-grid"]["ci90"]
            assert -design.MARGIN[q] < lo and hi < design.MARGIN[q]


def test_noise_too_large_to_settle_leaves_the_verdict_unresolved_and_the_abstract_gives_both():
    res = run(sd=40.0, seed=3)
    d = res["pooled"][ERCOT]["differences"]["alone-grid"]
    assert not d["equivalent"]
    assert d["verdict"] in ("unresolved", "different")
    assert res["abstract"]["gives_both_numbers"]


def test_the_bridge_holds_within_the_margin_and_fails_past_it():
    assert all(run(offset=3.0)["bridge"][m][q]["holds"] for m in design.FAMILIES for q in design.PRIMARY)
    res = run(offset=6.0)
    assert not any(res["bridge"][m][q]["holds"] for m in design.FAMILIES for q in design.PRIMARY)
    assert res["pooled"][ERCOT]["families"] == []
    assert res["pooled"][ERCOT]["differences"] == {}


def test_talaricos_share_pools_both_models_whatever_its_bridge_shows():
    res = run(offset=6.0)
    assert not any(res["bridge"][m]["senate_dem_share"]["holds"] for m in design.FAMILIES)
    assert res["pooled"]["senate_dem_share"]["families"] == list(design.FAMILIES)
    assert "verdict" not in res["pooled"]["senate_dem_share"]["differences"]["alone-grid"]


def test_a_file_without_both_jumps_for_every_pooled_model_drops_out_of_that_difference():
    rows = [r for r in mock_rows(sd=1.0) if not (r["file"] == "opus-3" and r["family"] == "sol" and r["arm"] == "alone" and r["key"] == "dem_50.5")]
    res = A.analyze(rows, mock_reference())
    assert res["pooled"][ERCOT]["differences"]["alone-grid"]["n"] == 15
    assert res["pooled"][ERCOT]["differences"]["told-grid"]["n"] == 16
    assert res["by_family"]["opus"][ERCOT]["differences"]["alone-grid"]["n"] == 16


def test_a_bridge_with_a_missing_run_does_not_hold():
    ref = mock_reference()
    ref["runs"]["sol-9"] = {"family": "sol", "questions": {q: {"jump": 0.0} for q in QUESTIONS}}
    br = A.analyze(mock_rows(sd=1.0), ref)["bridge"]
    assert not br["sol"][ERCOT]["complete"] and not br["sol"][ERCOT]["holds"]
    assert br["opus"][ERCOT]["holds"]


def test_a_primary_with_no_pooled_result_enters_holm_at_p_1():
    ref = mock_reference()
    for run_ in ref["runs"].values():
        run_["questions"][ERCOT]["jump"] -= 9.0  # every bridge fails on ERCOT alone
    res = A.analyze(mock_rows(sd=1.0), ref)
    e = res["pooled"][ERCOT]["differences"].get("alone-grid", {})
    s = res["pooled"][SPECIAL]["differences"]["alone-grid"]
    assert res["pooled"][ERCOT]["families"] == []
    assert s["p_zero_holm"] == pytest.approx(min(1.0, 2 * s["p_zero"]))
    assert s["p_equivalent_holm"] == pytest.approx(min(1.0, 2 * s["p_equivalent"]))
    assert s["verdict"] == "equivalent"
    assert not e
    report = A.report(res)
    assert f"| `{ERCOT}` | no pooled result |" in report
    assert f"| `{SPECIAL}` | no pooled result |" not in report


def test_a_family_whose_bridge_fails_drops_out_of_the_pooled_result_only():
    ref = mock_reference()
    for label, run_ in ref["runs"].items():
        if run_["family"] == "sol":
            run_["questions"][ERCOT]["jump"] -= 9.0
    res = A.analyze(mock_rows({"alone": {ERCOT: 4.0}}, sd=1.0), ref)
    assert res["pooled"][ERCOT]["families"] == ["opus"]
    assert res["by_family"]["sol"][ERCOT]["differences"]["alone-grid"]["n"] == 16


def test_the_cross_table_splits_research_from_reasoning():
    res = run(sd=0.0)
    cross = res["cross"][ERCOT]
    t = cross["jump_by_source_then_answerer"]
    for src in design.FAMILIES:
        for m in design.FAMILIES:
            assert t[src][m] == pytest.approx(GRID_JUMP[m][ERCOT])
    assert cross["research_sol_minus_opus"] == pytest.approx(0.0)
    assert cross["reasoning_sol_minus_opus"]["mean"] == pytest.approx(GRID_JUMP["sol"][ERCOT] - GRID_JUMP["opus"][ERCOT])


def test_the_report_renders_in_every_case():
    for res in (run(), run({"alone": {ERCOT: 8.0}}), run(offset=9.0)):
        text = A.report(res, res)
        assert text.startswith("# The three arms on Texas: results")
        assert "not observations" in text


# ------------------------------------------------------------------------------------------ loading


def test_load_keeps_the_registered_replicates_and_strict_drops_repaired_and_read_answers(tmp_path):
    rows = mock_rows(replicates=4, labels=("opus-1",))
    rows[0]["repaired"] = "1"
    rows[1]["prior_read"] = "1"
    path = tmp_path / "answers.csv"
    with path.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=collect.ANSWER_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    assert len(A.load(path)) == len(rows)
    assert all(r["replicate"] <= 3 for r in A.load(path, max_replicate=3))
    assert len(A.load(path, strict=True)) == len(rows) - 2


def test_main_writes_results_from_the_store(monkeypatch):
    paths.OUTPUTS.mkdir(parents=True)
    rows = mock_rows(sd=1.0)
    with (paths.OUTPUTS / "answers.csv").open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=collect.ANSWER_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    import json

    ref = paths.OUTPUTS / "reference.json"
    ref.write_text(json.dumps(mock_reference()))
    monkeypatch.setattr(paths, "DESIGN", paths.OUTPUTS)
    assert A.main() == 0
    out = json.loads((paths.OUTPUTS / "results.json").read_text())
    assert out["main"]["pooled"][ERCOT]["differences"]["alone-grid"]["verdict"] == "equivalent"
    assert out["registration"] == {"registered": False, "stamped": False, "changed": []}
    assert "Registration: none found" in (paths.OUTPUTS / "results.md").read_text()
    assert math.isclose(out["main"]["contexts"], len({r["context"] for r in rows}))
