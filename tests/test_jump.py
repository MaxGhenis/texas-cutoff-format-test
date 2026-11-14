"""cutoff.jump: the registered jump and the measure of a Talarico answer.

Every input in this file is MOCK: Hypothesis makes it up or a comment works it out by hand, and no
model gave any of it. Only the last two sections read real numbers (the Texas repository's own
sampler and the sealed runs' published jumps), and each of their tests skips on a machine that
lacks those files.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy import integrate

from cutoff import design, jump, paths, power, prompts, sources

# Hypothesis draws the same examples on every run, so a failure reproduces; no deadline, because the
# host that runs the suite is often busy.
PROPERTY = settings(max_examples=200, deadline=None, derandomize=True)

LO, HI = jump.SENATE_BOUNDS

# MOCK answers at the six cells: any finite numbers, in a range far wider than a forecast's.
mock_answers = st.lists(st.floats(-1000, 1000), min_size=6, max_size=6)
# MOCK Talarico answers that the answer check would accept: five quantiles that never decrease, inside
# the bounds. The sampled values make ties and quantiles on a bound common.
mock_quantiles = st.lists(
    st.one_of(st.floats(LO, HI), st.sampled_from([LO, HI, 50.0])), min_size=5, max_size=5
).map(sorted)


# ------------------------------------------------------------------------ independent implementations


def exact_line_at(xs, ys, at) -> Fraction:
    """A least-squares line's value at `at` in exact rational arithmetic: Cramer's rule on the two
    normal equations. It shares no step with `jump.side_weights`' centred formula."""
    xs, ys = [Fraction(x) for x in xs], [Fraction(y) for y in ys]
    n, sx, sy = len(xs), sum(xs), sum(ys)
    sxx, sxy = sum(x * x for x in xs), sum(x * y for x, y in zip(xs, ys))
    det = n * sxx - sx * sx
    return (sxx * sy - sx * sxy) / det + (n * sxy - sx * sy) / det * Fraction(at)


def exact_jump(values) -> Fraction:
    """The registered jump from two exact fits: the pass side's line at 50 minus the fail side's."""
    return exact_line_at(jump.PASS, values[3:], jump.THRESHOLD) - exact_line_at(jump.FAIL, values[:3], jump.THRESHOLD)


def polyfit_jump(values) -> float:
    """The registered jump from numpy.polyfit: one straight line a side, both read at 50."""
    x, y = np.array(jump.CELLS), np.asarray(values, dtype=float)
    fail = np.polyval(np.polyfit(x[:3], y[:3], 1), jump.THRESHOLD)
    passed = np.polyval(np.polyfit(x[3:], y[3:], 1), jump.THRESHOLD)
    return float(passed - fail)


def regression_jump(values) -> float:
    """The registered jump as one regression: an intercept and a slope on (share - 50) for each side.
    The gap between the two intercepts is the jump."""
    x = np.array(jump.CELLS) - jump.THRESHOLD
    above = (x > 0).astype(float)
    columns = np.column_stack([1 - above, (1 - above) * x, above, above * x])
    beta = np.linalg.lstsq(columns, np.asarray(values, dtype=float), rcond=None)[0]
    return float(beta[2] - beta[0])


def tail_ends(q, lo, hi) -> tuple[float, float]:
    """Where the docstring puts a distribution's ends, one number at a time: the outer segments' slopes
    carried to probability 0 and 1, then held inside the bounds."""
    low = q[0] - (q[1] - q[0]) / (0.25 - 0.05) * 0.05
    high = q[4] + (q[4] - q[3]) / (0.95 - 0.75) * 0.05
    return max(low, lo), min(high, hi)


def numeric_means(q, lo, hi) -> tuple[float, float]:
    """The mean of the docstring's distribution by two numeric integrations of its quantile function
    over probability: adaptive quadrature, and a midpoint sum on 2,000 equal steps. The knots sit on
    step edges (0.05 = 100 steps), so the midpoint sum is exact for straight segments."""
    low, high = tail_ends(q, lo, hi)
    probs = [0.0, 0.05, 0.25, 0.50, 0.75, 0.95, 1.0]
    knots = [low, *q, high]
    area, _ = integrate.quad(lambda u: np.interp(u, probs, knots), 0.0, 1.0, points=probs[1:-1], limit=200)
    steps = (np.arange(2000) + 0.5) / 2000
    return float(area), float(np.interp(steps, probs, knots).mean())


# ------------------------------------------------------------------------------------------ constants


def test_three_cells_sit_on_each_side_of_the_threshold_and_mirror_each_other():
    assert jump.CELLS == jump.FAIL + jump.PASS
    assert list(jump.CELLS) == sorted(jump.CELLS)
    assert len(jump.FAIL) == len(jump.PASS) == 3
    assert all(c < jump.THRESHOLD for c in jump.FAIL) and all(c > jump.THRESHOLD for c in jump.PASS)
    # The cells mirror about 50: 44 and 56, 47 and 53, 49.5 and 50.5.
    assert [a + b for a, b in zip(jump.CELLS, reversed(jump.CELLS))] == [100.0] * 6


def test_keys_name_the_cells_as_the_prompts_do():
    assert jump.KEYS == ("dem_44.0", "dem_47.0", "dem_49.5", "dem_50.5", "dem_53.0", "dem_56.0")
    assert jump.KEYS == tuple(prompts.cell_key(c) for c in jump.CELLS)


def test_every_question_has_one_kind_a_direction_and_a_scale():
    assert set(jump.BINARY) | set(jump.QUANTITY) == set(jump.QUESTIONS)
    assert not set(jump.BINARY) & set(jump.QUANTITY)
    assert set(jump.DIRECTION) == set(jump.SCALE) == set(jump.QUESTIONS)
    assert set(jump.DIRECTION.values()) <= {-1, +1}
    # The registered directions: a Hinojosa win lowers the chance ERCOT lifts its pause and raises
    # the chance of a special session.
    assert jump.DIRECTION["ercot_pause_lifted"] == -1
    assert jump.DIRECTION["special_session_data_centers"] == +1
    # A probability enters in points; Talarico's share is in points already.
    assert all(jump.SCALE[q] == 100.0 for q in jump.BINARY)
    assert all(jump.SCALE[q] == 1.0 for q in jump.QUANTITY)


def test_quantile_levels_rise_and_mirror_about_the_median():
    assert jump.QUANTILES == (0.05, 0.25, 0.50, 0.75, 0.95)
    assert [a + b for a, b in zip(jump.QUANTILES, reversed(jump.QUANTILES))] == pytest.approx([1.0] * 5)
    assert jump.SENATE_BOUNDS == (30.0, 70.0)


# -------------------------------------------------------------------------------------------- weights


def test_weights_equal_an_exact_least_squares_fit():
    # The answer "1 at one cell, 0 elsewhere" has that cell's weight as its jump. Exact arithmetic gives
    # 47/182, -67/182, -162/182 and their mirror images.
    exact = [exact_jump([1 if i == j else 0 for j in range(6)]) for i in range(6)]
    assert exact == [Fraction(n, 182) for n in (47, -67, -162, 162, 67, -47)]
    # Floats carry about 1e-16 a step; 1e-14 leaves room and no wrong weight comes that close.
    assert jump.WEIGHTS == pytest.approx([float(w) for w in exact], abs=1e-14)


@pytest.mark.parametrize("fit", [polyfit_jump, regression_jump])
def test_weights_equal_a_numpy_least_squares_fit(fit):
    for i in range(6):
        unit = [1.0 if i == j else 0.0 for j in range(6)]
        # numpy solves these small systems to about 1e-13; 1e-10 leaves room.
        assert fit(unit) == pytest.approx(jump.WEIGHTS[i], abs=1e-10)


def test_weights_are_the_fail_side_negated_then_the_pass_side():
    assert jump.WEIGHTS.shape == (6,)
    assert jump.WEIGHTS[:3] == pytest.approx(-jump.side_weights(jump.FAIL))
    assert jump.WEIGHTS[3:] == pytest.approx(jump.side_weights(jump.PASS))


def test_each_side_sums_to_one_and_all_six_sum_to_zero():
    # A side's weights sum to 1, so a constant answer keeps its level; the fail side enters negated.
    assert jump.WEIGHTS[3:].sum() == pytest.approx(1.0, abs=1e-12)
    assert jump.WEIGHTS[:3].sum() == pytest.approx(-1.0, abs=1e-12)
    assert jump.WEIGHTS.sum() == pytest.approx(0.0, abs=1e-12)


def test_weights_mirror_with_the_cells():
    # The cells mirror about 50, so the weight at 50 + d is minus the weight at 50 - d.
    assert jump.WEIGHTS == pytest.approx(-jump.WEIGHTS[::-1], abs=1e-14)


def test_the_docstring_prints_the_weights_to_four_decimals():
    printed = re.search(
        r"J = ([\d.]+) \(y50\.5 - y49\.5\) \+ ([\d.]+) \(y53 - y47\) - ([\d.]+) \(y56 - y44\)", jump.__doc__
    )
    assert printed, "the module docstring no longer states the jump as one weighted sum"
    assert printed.groups() == ("0.8901", "0.3681", "0.2582")
    w = dict(zip(jump.CELLS, jump.WEIGHTS))
    # The docstring's formula, term by term: +0.8901 at 50.5 and -0.8901 at 49.5, and so on.
    assert [f"{w[50.5]:.4f}", f"{w[53.0]:.4f}", f"{-w[56.0]:.4f}"] == list(printed.groups())
    assert [f"{-w[49.5]:.4f}", f"{-w[47.0]:.4f}", f"{w[44.0]:.4f}"] == list(printed.groups())


def test_squared_weights_sum_to_the_1_989_that_design_and_power_use():
    total = float(np.sum(jump.WEIGHTS**2))
    assert total == pytest.approx(181 / 91, abs=1e-12)  # exact: 2 (47^2 + 67^2 + 162^2) / 182^2
    assert f"{total:.3f}" == "1.989"
    assert design.SUM_W2 == pytest.approx(total, abs=1e-15)
    stated = re.search(r"S = sum of squared weights = ([\d.]+)\.\n", power.__doc__)
    assert stated and stated.group(1) == f"{total:.3f}"


@st.composite
def mock_side(draw):
    """MOCK cells for one side: two to six distinct shares on a half-point grid from 40 to 60, a share
    to read the line at, and an answer at each cell."""
    n = draw(st.integers(2, 6))
    xs = [k / 2 for k in draw(st.lists(st.integers(80, 120), min_size=n, max_size=n, unique=True))]
    ys = draw(st.lists(st.floats(-1000, 1000), min_size=n, max_size=n))
    return xs, ys, draw(st.floats(40, 60))


@PROPERTY
@given(side=mock_side())
def test_side_weights_read_a_least_squares_line_at_any_share(side):
    xs, ys, at = side
    w = jump.side_weights(xs, at)
    # With cells half a point apart or more and `at` within 20 points, no weight exceeds 41, so sums of
    # up to six products of weights and answers below 1,000 round off below 1e-9.
    assert w.sum() == pytest.approx(1.0, abs=1e-9)  # a constant answer keeps its level
    assert float(w @ np.array(xs)) == pytest.approx(at, abs=1e-9)  # the line y = x is read exactly
    assert float(w @ np.array(ys)) == pytest.approx(float(exact_line_at(xs, ys, at)), abs=1e-7)


def test_side_weights_at_the_mean_share_average_the_answers():
    # A least-squares line passes through the point of means.
    assert jump.side_weights(jump.FAIL, at=np.mean(jump.FAIL)) == pytest.approx([1 / 3] * 3)


def test_side_weights_with_two_cells_draw_the_line_through_both():
    # Through (40, y1) and (50, y2), the value at 55 is y2 + (y2 - y1) / 2 = -0.5 y1 + 1.5 y2.
    assert jump.side_weights([40.0, 50.0], at=55.0) == pytest.approx([-0.5, 1.5])


# ----------------------------------------------------------------------------------------------- jump


@PROPERTY
@given(values=mock_answers)
def test_jump_equals_the_gap_between_two_least_squares_lines(values):
    got = jump.jump(values)
    assert got == pytest.approx(float(jump.WEIGHTS @ np.array(values)), abs=1e-9)
    # Exact arithmetic first. The weights sum to 3.03 in size, so answers below 1,000 give a jump below
    # 3,033 and float error near 1e-12.
    assert got == pytest.approx(float(exact_jump(values)), abs=1e-9)
    # numpy's solvers carry about 1e-12 of the answers' size (their systems have condition numbers
    # below 100); 1e-6 leaves room, and a weight wrong in its fourth decimal would miss by 1e-4 a point.
    scale = max(1.0, max(abs(v) for v in values))
    assert got == pytest.approx(polyfit_jump(values), abs=1e-9 * scale)
    assert got == pytest.approx(regression_jump(values), abs=1e-9 * scale)


@PROPERTY
@given(intercept=st.floats(-1000, 1000), slope=st.floats(-100, 100))
def test_a_straight_line_through_all_six_cells_has_no_jump(intercept, slope):
    line = [intercept + slope * c for c in jump.CELLS]
    # The answers stay below 6,600, so rounding stays below 1e-10.
    assert jump.jump(line) == pytest.approx(0.0, abs=1e-8)


@PROPERTY
@given(intercept=st.floats(-1000, 1000), slope=st.floats(-100, 100), step=st.floats(-1000, 1000))
def test_a_step_at_the_threshold_is_the_jump(intercept, slope, step):
    stepped = [intercept + slope * c + (step if c > jump.THRESHOLD else 0.0) for c in jump.CELLS]
    assert jump.jump(stepped) == pytest.approx(step, abs=1e-8)


@PROPERTY
@given(
    fail=st.tuples(st.floats(-1000, 1000), st.floats(-100, 100)),
    passed=st.tuples(st.floats(-1000, 1000), st.floats(-100, 100)),
)
def test_a_line_on_each_side_gives_the_gap_between_them_at_50(fail, passed):
    # "Each side's line reproduces any straight line through that side's cells exactly."
    values = [fail[0] + fail[1] * c for c in jump.FAIL] + [passed[0] + passed[1] * c for c in jump.PASS]
    gap = (passed[0] + passed[1] * jump.THRESHOLD) - (fail[0] + fail[1] * jump.THRESHOLD)
    assert jump.jump(values) == pytest.approx(gap, abs=1e-8)


@PROPERTY
@given(u=mock_answers, v=mock_answers, a=st.floats(-10, 10), b=st.floats(-10, 10))
def test_jump_is_linear(u, v, a, b):
    mixed = a * np.array(u) + b * np.array(v)
    # Sizes stay below 2e4 x 3.03, so rounding stays below 1e-10.
    assert jump.jump(mixed) == pytest.approx(a * jump.jump(u) + b * jump.jump(v), abs=1e-7)


@PROPERTY
@given(values=mock_answers, intercept=st.floats(-1000, 1000), slope=st.floats(-100, 100))
def test_adding_a_straight_line_to_the_answers_leaves_the_jump(values, intercept, slope):
    shifted = [v + intercept + slope * c for v, c in zip(values, jump.CELLS)]
    assert jump.jump(shifted) == pytest.approx(jump.jump(values), abs=1e-7)


@PROPERTY
@given(values=mock_answers)
def test_mirroring_the_answers_about_50_flips_the_jump(values):
    assert jump.jump(values[::-1]) == pytest.approx(-jump.jump(values), abs=1e-9)


@PROPERTY
@given(values=mock_answers)
def test_jump_stays_within_the_weights_total_size(values):
    reach = float(np.abs(jump.WEIGHTS).sum()) * max(abs(v) for v in values)
    assert abs(jump.jump(values)) <= reach + 1e-9


@PROPERTY
@given(contexts=st.lists(mock_answers, min_size=1, max_size=6))
def test_the_jump_of_cell_means_is_the_mean_of_the_contexts_jumps(contexts):
    # The analysis relies on this in the grid arm: averaging answers first or jumps first is the same.
    grid = np.array(contexts)
    assert jump.jump(grid.mean(axis=0)) == pytest.approx(np.mean([jump.jump(row) for row in grid]), abs=1e-8)


def test_jump_takes_a_list_a_tuple_or_an_array_and_returns_a_float():
    values = [10.0, 12.0, 15.0, 40.0, 41.0, 43.0]  # MOCK
    got = jump.jump(values)
    assert type(got) is float
    assert jump.jump(tuple(values)) == got == jump.jump(np.array(values))


@pytest.mark.parametrize(
    "bad",
    [[], [1.0], [1.0] * 5, [1.0] * 7, [[1.0] * 6], [[1.0]] * 6, [[1.0] * 3] * 2, 5.0],
    ids=["none", "one", "five", "seven", "row", "column", "two-by-three", "scalar"],
)
def test_jump_refuses_anything_but_six_answers(bad):
    with pytest.raises(ValueError, match="six answers"):
        jump.jump(bad)


# ----------------------------------------------------------------------------- Talarico distributions


def test_knots_add_a_tail_end_at_probability_0_and_1():
    probs, values = jump.quantity_knots(jump.QUANTILES, [[40.0, 42.0, 45.0, 50.0, 60.0]], LO, HI)  # MOCK
    assert probs == pytest.approx([0.0, 0.05, 0.25, 0.50, 0.75, 0.95, 1.0])
    # First segment: 2 points over 0.20 of probability, so 0.5 over the last 0.05: 40 - 0.5 = 39.5.
    # Last segment: 10 points over 0.20, so 2.5 over the last 0.05: 60 + 2.5 = 62.5.
    assert values == pytest.approx(np.array([[39.5, 40.0, 42.0, 45.0, 50.0, 60.0, 62.5]]))


def test_mean_of_a_hand_worked_distribution():
    # Knots 39.5, 40, 42, 45, 50, 60, 62.5 at probabilities 0, .05, .25, .5, .75, .95, 1. Each segment
    # adds its width times the mean of its ends:
    # .05 x 39.75 + .20 x 41 + .25 x 43.5 + .25 x 47.5 + .20 x 55 + .05 x 61.25
    # = 1.9875 + 8.2 + 10.875 + 11.875 + 11 + 3.0625 = 47.
    assert jump.quantity_mean([40.0, 42.0, 45.0, 50.0, 60.0]) == pytest.approx(47.0, abs=1e-12)


def test_bounds_clip_the_tails():
    # The slopes would carry the tails to 27.5 and 72.5; the bounds hold them at 30 and 70.
    _, values = jump.quantity_knots(jump.QUANTILES, [[30.0, 40.0, 50.0, 60.0, 70.0]], LO, HI)
    assert values == pytest.approx(np.array([[30.0, 30.0, 40.0, 50.0, 60.0, 70.0, 70.0]]))
    assert jump.quantity_mean([30.0, 40.0, 50.0, 60.0, 70.0]) == pytest.approx(50.0, abs=1e-12)
    # One point inside each bound: 31 - 2 = 29 becomes 30, and 69.5 + 2.875 = 72.375 becomes 70.
    # .05 x 30.5 + .20 x 35 + .25 x 44.5 + .25 x 54 + .20 x 63.75 + .05 x 69.75 = 49.3875.
    assert jump.quantity_mean([31.0, 39.0, 50.0, 58.0, 69.5]) == pytest.approx(49.3875, abs=1e-12)
    # With room to spare the same answer keeps its unclipped tails, 29 and 72.375, and a lower mean
    # on the left, a higher one on the right: .05 x (30 + 71.1875) + the middle four = 49.421875.
    assert jump.quantity_mean([31.0, 39.0, 50.0, 58.0, 69.5], lo=0.0, hi=100.0) == pytest.approx(49.421875, abs=1e-12)


@pytest.mark.parametrize("x", [LO, 41.25, 50.0, HI])
def test_five_equal_quantiles_put_the_whole_distribution_at_one_share(x):
    _, values = jump.quantity_knots(jump.QUANTILES, [[x] * 5], LO, HI)
    assert values.tolist() == [[x] * 7]
    assert jump.quantity_mean([x] * 5) == x


def test_ties_make_flat_stretches_and_flat_tails():
    # MOCK: 45 up to the median, 55 from the 75th percentile. Both outer segments are flat, so the
    # tails stay at 45 and 55: .05 x 45 + .20 x 45 + .25 x 45 + .25 x 50 + .20 x 55 + .05 x 55 = 48.75.
    assert jump.quantity_mean([45.0, 45.0, 45.0, 55.0, 55.0]) == pytest.approx(48.75, abs=1e-12)


@PROPERTY
@given(q=mock_quantiles)
def test_mean_equals_numeric_integration_of_the_quantile_function(q):
    by_quadrature, by_midpoints = numeric_means(q, LO, HI)
    # Both integrations are exact for straight segments up to rounding, about 1e-13 at these sizes.
    assert jump.quantity_mean(q) == pytest.approx(by_quadrature, abs=1e-9)
    assert jump.quantity_mean(q) == pytest.approx(by_midpoints, abs=1e-9)


@PROPERTY
@given(
    fractions=st.lists(st.floats(0, 1), min_size=5, max_size=5).map(sorted),
    lo=st.floats(-100, 100),
    width=st.floats(1, 100),
)
def test_mean_equals_numeric_integration_under_any_bounds(fractions, lo, width):
    hi = lo + width
    q = [lo + f * width for f in fractions]  # MOCK quantiles inside MOCK bounds
    q[-1] = min(q[-1], hi)  # rounding may put the top quantile a hair past the bound
    by_quadrature, by_midpoints = numeric_means(q, lo, hi)
    assert jump.quantity_mean(q, lo, hi) == pytest.approx(by_quadrature, abs=1e-9)
    assert jump.quantity_mean(q, lo, hi) == pytest.approx(by_midpoints, abs=1e-9)


@PROPERTY
@given(q=mock_quantiles)
def test_knots_never_decrease_and_stay_inside_the_bounds(q):
    probs, values = jump.quantity_knots(jump.QUANTILES, [q], LO, HI)
    v = values[0]
    assert v.shape == probs.shape == (7,)
    assert list(v[1:6]) == q  # the stated quantiles pass through untouched
    assert (v[0], v[6]) == pytest.approx(tail_ends(q, LO, HI), abs=1e-12)
    assert all(a <= b for a, b in zip(v, v[1:]))  # a quantile function never falls
    assert LO <= v[0] and v[6] <= HI
    assert v[0] <= jump.quantity_mean(q) <= v[6]


@PROPERTY
@given(q=mock_quantiles, i=st.integers(0, 4), rise=st.floats(0, 40))
def test_raising_a_quantile_never_lowers_the_mean(q, i, rise):
    ceiling = HI if i == 4 else q[i + 1]  # stay a valid answer: in order and inside the bounds
    raised = list(q)
    raised[i] = min(q[i] + rise, ceiling)
    step = raised[i] - q[i]
    gain = jump.quantity_mean(raised) - jump.quantity_mean(q)
    # Rounding at these sizes is below 1e-13.
    assert gain >= -1e-12
    # Sharper: each quantile carries between an eighth and a quarter of the mean. The median's two
    # segments weigh .25 / 2 each; an outer quantile weighs (.20 + .05) / 2 when the bound holds its
    # tail, and more when the tail moves with it.
    assert step / 8 - 1e-9 <= gain <= step / 4 + 1e-9


@PROPERTY
@given(q=mock_quantiles)
def test_mirroring_a_distribution_mirrors_its_mean(q):
    # The levels mirror about the median and the bounds about 50, so the answer read from the top
    # down is the same distribution reflected.
    mirrored = [LO + HI - x for x in reversed(q)]
    assert jump.quantity_mean(mirrored) == pytest.approx(LO + HI - jump.quantity_mean(q), abs=1e-9)


@PROPERTY
@given(q=mock_quantiles, scale=st.floats(0.1, 10), shift=st.floats(-100, 100))
def test_rescaling_shares_and_bounds_rescales_the_mean(q, scale, shift):
    moved = [scale * x + shift for x in q]
    got = jump.quantity_mean(moved, scale * LO + shift, scale * HI + shift)
    # Sizes stay below 800, so rounding stays below 1e-12.
    assert got == pytest.approx(scale * jump.quantity_mean(q) + shift, abs=1e-8)


@PROPERTY
@given(rows=st.lists(mock_quantiles, min_size=1, max_size=5))
def test_knots_for_many_answers_match_each_answer_alone(rows):
    _, together = jump.quantity_knots(jump.QUANTILES, rows, LO, HI)
    assert together.shape == (len(rows), 7)
    for row, values in zip(rows, together):
        _, alone = jump.quantity_knots(jump.QUANTILES, [row], LO, HI)
        assert values.tolist() == alone[0].tolist()


def test_mean_uses_the_senate_bounds_by_default_and_returns_a_float():
    q = [30.5, 33.0, 50.0, 67.0, 69.5]  # MOCK: both tails reach the bounds
    assert jump.quantity_mean(q) == jump.quantity_mean(q, 30.0, 70.0)
    assert jump.quantity_mean(q) != jump.quantity_mean(q, 0.0, 70.0)  # moving one bound moves the mean
    assert type(jump.quantity_mean(q)) is float


@pytest.mark.parametrize("bad", [[], [50.0], [45.0, 55.0], [40.0, 50.0, 60.0], [35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0]])
def test_mean_refuses_anything_but_five_quantiles(bad):
    with pytest.raises((ValueError, IndexError)):
        jump.quantity_mean(bad)


# --------------------------------------------------------------------------------------- answer_value


@PROPERTY
@given(p=st.floats(0, 1), question=st.sampled_from(jump.BINARY))
def test_a_probability_enters_in_points(p, question):
    value = jump.answer_value(question, p)
    assert type(value) is float
    assert value == p * 100.0
    assert 0.0 <= value <= 100.0


@PROPERTY
@given(q=mock_quantiles)
def test_a_talarico_answer_enters_as_its_distributions_mean(q):
    assert jump.answer_value("senate_dem_share", q) == jump.quantity_mean(q)
    assert LO <= jump.answer_value("senate_dem_share", q) <= HI


@pytest.mark.parametrize("unknown", ["tax_exemption_cut", "senate", "ERCOT_PAUSE_LIFTED", "", None])
def test_an_unknown_question_raises(unknown):
    with pytest.raises(KeyError):
        jump.answer_value(unknown, 0.5)


# --------------------------------------------------- the Texas repository's sampler (skips without it)


@pytest.fixture(scope="module")
def texas_dists():
    """The Texas repository's own samplers. `quantity_knots` says it copies one of them."""
    path = paths.PUBLIC_TEXAS / "src" / "i86" / "dists.py"
    if not path.exists():
        pytest.skip("the public Texas repository is not on this machine")
    spec = importlib.util.spec_from_file_location("texas_i86_dists", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        pytest.skip(f"the Texas repository's samplers do not load on their own: {exc}")
    return module


@PROPERTY
@given(q=mock_quantiles)
def test_knots_match_the_texas_repositorys(texas_dists, q):
    ours = jump.quantity_knots(jump.QUANTILES, [q], LO, HI)
    theirs = texas_dists.quantity_knots(np.array(jump.QUANTILES), np.array([q]), LO, HI)
    # A copy runs the same arithmetic, so the knots agree to the last bit.
    assert ours[0].tolist() == theirs[0].tolist()
    assert ours[1].tolist() == theirs[1].tolist()


@PROPERTY
@given(q=mock_quantiles)
def test_mean_matches_the_mean_of_the_texas_samplers_draws(texas_dists, q):
    # One draw at the middle of each of 2,000 equal steps of probability. The knots sit on step edges,
    # so the draws' mean is the distribution's mean up to rounding.
    steps = (np.arange(2000) + 0.5) / 2000
    draws = texas_dists.sample_quantity(jump.QUANTILES, [q], LO, HI, steps)
    assert jump.quantity_mean(q) == pytest.approx(float(draws.mean()), abs=1e-9)


# --------------------------------------------------- the sealed runs' own numbers (skip without them)


@pytest.fixture(scope="module")
def reference():
    path = paths.DESIGN / "reference.json"
    if not path.exists():
        pytest.skip("design/reference.json has not been built")
    return json.loads(path.read_text())


def test_reference_jumps_are_the_registered_jump_of_the_reference_cells(reference):
    assert reference["cells"] == list(jump.CELLS)
    assert set(reference["runs"]) == set(sources.ACCEPTED)
    for label, run in reference["runs"].items():
        assert run["family"] == sources.family(label)
        assert set(run["questions"]) == set(jump.QUESTIONS)
        for q, rec in run["questions"].items():
            assert len(rec["cells"]) == 6
            assert rec["jump"] == pytest.approx(jump.jump(rec["cells"]), abs=1e-9), (label, q)
            assert rec["signed"] == pytest.approx(rec["jump"] * jump.DIRECTION[q], abs=1e-12), (label, q)
        for q in jump.BINARY:
            assert all(0.0 <= v <= 100.0 for v in run["questions"][q]["cells"]), (label, q)
        for q in jump.QUANTITY:
            assert all(LO <= v <= HI for v in run["questions"][q]["cells"]), (label, q)


def test_reference_jumps_match_the_texas_repositorys_fits(reference):
    path = paths.PUBLIC_TEXAS / "outputs" / "rd.csv"
    if not path.exists():
        pytest.skip("the public Texas repository's outputs/rd.csv is not on this machine")
    fits: dict = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            fits.setdefault((row["run"], row["question"]), []).append(float(row["fit_jump"]))
    for label in sources.ACCEPTED:
        for q in jump.BINARY:
            ours = reference["runs"][label]["questions"][q]["jump"]
            # rd.csv keeps probabilities, so its fit is the jump over 100. A run and question may
            # have more than one row; any of them may match.
            assert any(abs(ours - 100.0 * theirs) <= 1e-9 for theirs in fits[(label, q)]), (label, q)


def test_reference_matches_the_papers_texas_data(reference):
    path = paths.HOME / "reviews" / "dc-i86-llm-forecast" / "paper" / "data" / "texas.json"
    if not path.exists():
        pytest.skip("the paper's data/texas.json is not on this machine")
    paper = json.loads(path.read_text())["runs"]
    for label in sources.ACCEPTED:
        for q in jump.QUESTIONS:
            ours, theirs = reference["runs"][label]["questions"][q], paper[label][q]
            assert ours["jump"] == pytest.approx(jump.SCALE[q] * theirs["ols_jump"], abs=1e-9), (label, q)
            cells = [jump.SCALE[q] * theirs["cells"][f"{c:.1f}"] for c in jump.CELLS]
            # For Talarico's share these are the means `quantity_mean` gives; the paper computed its
            # own from the same quantiles.
            assert ours["cells"] == pytest.approx(cells, abs=1e-9), (label, q)
