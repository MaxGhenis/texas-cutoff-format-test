"""Reading a context's answer: the check against its template, which block counts, and the two
registered repairs. Every answer here is MOCK text."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cutoff import response as R
from cutoff.jump import BINARY, CELLS, KEYS, QUANTITY, QUESTIONS


def answer(keys=KEYS, p=0.4, q=(44.0, 47.0, 49.0, 51.0, 54.0), cell=None, prior="none"):
    nodes = {}
    for question in QUESTIONS:
        if question in BINARY:
            fc = {k: {"p": p} for k in keys}
        else:
            fc = {k: dict(zip(R.QUANTILE_KEYS, q)) for k in keys}
        nodes[question] = {"forecasts": fc, "reasoning": "MOCK"}
    obj = {"forecaster": {"prior_context": prior}, "nodes": nodes}
    if cell is not None:
        obj["scenario"] = {"hinojosa_share": cell, "winner": R.expected_winner(cell).title()}
    return obj


def fenced(obj, tag="json") -> str:
    return f"```{tag}\n{json.dumps(obj, indent=1)}\n```"


# ----------------------------------------------------------------------------------------- the check


def test_a_filled_grid_template_passes():
    a = R.parse(answer(), KEYS)
    assert set(a.values) == set(QUESTIONS)
    for question in BINARY:
        assert a.values[question] == {k: 0.4 for k in KEYS}
    for question in QUANTITY:
        assert a.values[question][KEYS[0]] == [44.0, 47.0, 49.0, 51.0, 54.0]


@pytest.mark.parametrize("cell", CELLS)
def test_an_isolated_answer_must_restate_its_scenario(cell):
    key = (KEYS[CELLS.index(cell)],)
    assert R.parse(answer(key, cell=cell), key, cell).scenario["hinojosa_share"] == cell
    bad = answer(key, cell=cell)
    bad["scenario"]["winner"] = R.expected_winner(100 - cell).title()
    with pytest.raises(R.ResponseError):
        R.parse(bad, key, cell)
    missing = answer(key)
    with pytest.raises(R.ResponseError, match="scenario"):
        R.parse(missing, key, cell)
    fraction = answer(key, cell=cell)
    fraction["scenario"]["hinojosa_share"] = cell / 100
    assert R.parse(fraction, key, cell)
    off = answer(key, cell=cell)
    off["scenario"]["hinojosa_share"] = cell + 1
    with pytest.raises(R.ResponseError):
        R.parse(off, key, cell)


def test_both_names_in_the_winner_fail():
    cell = 53.0
    a = answer(("dem_53.0",), cell=cell)
    a["scenario"]["winner"] = "Hinojosa beats Abbott"
    with pytest.raises(R.ResponseError, match="winner"):
        R.parse(a, ("dem_53.0",), cell)


@pytest.mark.parametrize(
    "change, problem",
    [
        (lambda a: a["forecaster"].pop("prior_context"), "prior_context"),
        (lambda a: a["nodes"].pop("ercot_pause_lifted"), "ercot_pause_lifted"),
        (lambda a: a["nodes"]["ercot_pause_lifted"]["forecasts"].update({"dem_60.0": {"p": 0.1}}), "unexpected"),
        (lambda a: a["nodes"]["ercot_pause_lifted"]["forecasts"]["dem_44.0"].update({"p": 1.2}), "probability"),
        (lambda a: a["nodes"]["ercot_pause_lifted"]["forecasts"]["dem_44.0"].update({"p": "40%"}), "probability"),
        (lambda a: a["nodes"]["senate_dem_share"]["forecasts"]["dem_44.0"].update({"p05": 60.0}), "decrease"),
        (lambda a: a["nodes"]["senate_dem_share"]["forecasts"]["dem_44.0"].update({"p95": 75.0}), "lie in"),
        (lambda a: a["nodes"].update({"extra_question": {"forecasts": {}}}), "unexpected questions"),
    ],
)
def test_each_defect_fails_with_its_problem_named(change, problem):
    a = answer()
    change(a)
    with pytest.raises(R.ResponseError, match=problem):
        R.parse(a, KEYS)


@settings(max_examples=300, deadline=None)
@given(st.floats(0.0, 1.0, allow_nan=False))
def test_a_number_or_a_plain_numeric_string_reads_as_itself(x):
    assert R._number(x) == x
    assert R._number(repr(x)) == x
    assert R._number(f"  {x!r} ") == x


@pytest.mark.parametrize("bad", ["1%", "0.5%", "0,1", "1,000", "", "abc", "nan", "inf", True, False, None, [0.1], {"p": 1}, 10**400, "1" * 400])
def test_anything_but_a_plain_number_reads_as_nothing(bad):
    assert R._number(bad) is None


# ------------------------------------------------------------------------------------- which block


@settings(max_examples=100, deadline=None)
@given(st.lists(st.floats(0.0, 1.0, allow_nan=False), min_size=1, max_size=4))
def test_the_last_block_that_names_nodes_counts(ps):
    text = "\n\nMOCK draft notes.\n\n".join(fenced(answer(p=p)) for p in ps)
    a, repairs = R.read_answer(text, KEYS)
    assert a.values["ercot_pause_lifted"]["dem_44.0"] == ps[-1]
    assert repairs == []


def test_a_passing_draft_does_not_stand_in_for_a_last_block_that_needs_a_repair():
    last = fenced(answer(p=0.99)).replace('"reasoning": "MOCK"\n  }', '"reasoning": "MOCK",\n  }', 1)
    assert last != fenced(answer(p=0.99))
    text = fenced(answer(p=0.11)) + "\nMOCK revision.\n" + last
    a, repairs = R.read_answer(text, KEYS)
    assert a.values["ercot_pause_lifted"]["dem_44.0"] == 0.99
    assert [r["repair"] for r in repairs] == ["trailing_comma"]


def test_a_last_block_that_does_not_parse_fails_the_answer():
    truncated = fenced(answer(p=0.99))[:-200] + "\n```"
    with pytest.raises(R.ResponseError, match="does not parse"):
        R.read_answer(fenced(answer(p=0.11)) + "\n" + truncated, KEYS)


@pytest.mark.parametrize("tag", ["", "json", "JSON", "text", "python"])
def test_a_fence_with_any_tag_pairs_with_its_own_closing_fence(tag):
    text = "```python\nweights = {1: 2}\n```\nMOCK.\n" + fenced(answer(p=0.3), tag)
    assert R.read_answer(text, KEYS)[0].values["ercot_pause_lifted"]["dem_44.0"] == 0.3


def test_an_unfenced_answer_reads_as_the_outermost_object():
    assert R.read_answer("MOCK preface " + json.dumps(answer(p=0.2)) + " MOCK end", KEYS)[0]


@pytest.mark.parametrize("text", ["no braces at all", "```json\n{\"nodes\": {\"a\": 1e999999}\n```"])
def test_no_object_or_an_unreadable_one_fails(text):
    with pytest.raises(R.ResponseError):
        R.read_answer(text, KEYS)


def test_an_integer_past_pythons_digit_limit_fails_as_a_response_error():
    text = '```json\n{"forecaster": {"prior_context": "none"}, "nodes": {"x": ' + "9" * 5000 + "}}\n```"
    with pytest.raises(R.ResponseError):
        R.read_answer(text, KEYS)


def test_a_huge_integer_probability_fails_as_a_response_error():
    a = json.dumps(answer()).replace('"p": 0.4', '"p": ' + "9" * 310, 1)
    with pytest.raises(R.ResponseError, match="probability"):
        R.read_answer(a, KEYS)


# ---------------------------------------------------------------------------------------- repairs

json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-1000, 1000) | st.floats(allow_nan=False, allow_infinity=False) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=6), inner, max_size=4),
    max_leaves=20,
)


def dumps_with_trailing_commas(v) -> str:
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{" + ", ".join(f"{json.dumps(k)}: {dumps_with_trailing_commas(x)}" for k, x in v.items()) + ", }"
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(dumps_with_trailing_commas(x) for x in v) + ",\n ]"
    return json.dumps(v)


@settings(max_examples=300, deadline=None)
@given(json_values)
def test_the_comma_repair_leaves_valid_json_alone_and_mends_trailing_commas(v):
    text = json.dumps(v)
    fixed, removed = R._strip_trailing_commas(text)
    assert (fixed, removed) == (text, [])
    messy = dumps_with_trailing_commas(v)
    assert json.loads(R._strip_trailing_commas(messy)[0]) == v


@settings(max_examples=200, deadline=None)
@given(st.text(alphabet=',}]{["\\ a', max_size=12))
def test_the_comma_repair_never_touches_a_string(s):
    obj = {"k": s}
    text = json.dumps(obj)
    assert R._strip_trailing_commas(text)[0] == text


def test_an_answer_that_passes_as_written_gets_no_repair():
    assert R.read_answer(fenced(answer()), KEYS)[1] == []


def test_a_stray_key_without_an_object_goes_and_is_recorded():
    a = answer()
    a["nodes"]["ercot_pause_lifted"]["forecasts"]["note"] = "MOCK"
    a["nodes"]["comment"] = None
    out, repairs = R.read_answer(fenced(a), KEYS)
    assert sorted((r["repair"], r["key"]) for r in repairs) == [("dropped_key", "comment"), ("dropped_key", "note")]
    assert set(out.values["ercot_pause_lifted"]) == set(KEYS)


def test_a_stray_key_that_holds_an_object_is_not_repaired():
    a = answer()
    a["nodes"]["ercot_pause_lifted"]["forecasts"]["dem_60.0"] = {"p": 0.5}
    with pytest.raises(R.ResponseError, match="unexpected forecast keys"):
        R.read_answer(fenced(a), KEYS)


def test_keys_for_each_arm():
    assert R.keys_for("grid", "all") == (KEYS, None)
    for c, k in zip(CELLS, KEYS):
        assert R.keys_for("alone", k) == ((k,), c)
        assert R.keys_for("told", k) == ((k,), c)
