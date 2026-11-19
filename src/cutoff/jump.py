"""The registered jump: lines fitted by least squares through the three cells on each side of 50%,
and the gap between them at 50%.

For cells at shares x with answers y, each side's line evaluated at 50% is a weighted sum of that
side's answers, with weights 1/3 + (50 - mean x)(x - mean x) / sum (x - mean x)^2. The jump is the
pass side's value at 50% minus the fail side's, so it is one fixed weighted sum of the six answers:

    J = 0.8901 (y50.5 - y49.5) + 0.3681 (y53 - y47) - 0.2582 (y56 - y44).

Each side's line reproduces any straight line through that side's cells exactly, so a straight line
through all six cells gives J = 0 and a step of size D at 50% gives J = D (tests/test_jump.py checks
both, and checks the weights against a least-squares fit).
"""

from __future__ import annotations

import numpy as np

CELLS = (44.0, 47.0, 49.5, 50.5, 53.0, 56.0)
FAIL = CELLS[:3]  # Abbott wins
PASS = CELLS[3:]  # Hinojosa wins
THRESHOLD = 50.0
KEYS = tuple(f"dem_{c:.1f}" for c in CELLS)

QUESTIONS = ("senate_dem_share", "ercot_pause_lifted", "special_session_data_centers")
BINARY = ("ercot_pause_lifted", "special_session_data_centers")
QUANTITY = ("senate_dem_share",)
# The registered directions: +1 where a Hinojosa win should raise the answer. A signed jump is the jump
# times its direction, so a positive signed jump points the registered way. Talarico's share has no
# registered direction; +1 leaves its jump as it is.
DIRECTION = {"ercot_pause_lifted": -1, "special_session_data_centers": +1, "senate_dem_share": +1}
# Probabilities enter in points (percent); Talarico's share is already in points of share.
SCALE = {"ercot_pause_lifted": 100.0, "special_session_data_centers": 100.0, "senate_dem_share": 1.0}

QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)
SENATE_BOUNDS = (30.0, 70.0)


def side_weights(xs, at: float = THRESHOLD) -> np.ndarray:
    """Weights that turn a side's answers into its least-squares line's value at `at`."""
    xs = np.asarray(xs, dtype=float)
    dev = xs - xs.mean()
    return 1.0 / len(xs) + (at - xs.mean()) * dev / (dev**2).sum()


WEIGHTS = np.concatenate([-side_weights(FAIL), side_weights(PASS)])


def jump(values) -> float:
    """The jump for six answers in CELLS order."""
    v = np.asarray(values, dtype=float)
    if v.shape != (6,):
        raise ValueError(f"need six answers in cell order, got shape {v.shape}")
    return float(WEIGHTS @ v)


def quantity_knots(levels, xs, lo: float, hi: float):
    """The quantile function the Texas simulator draws from: straight lines between the stated
    quantiles, and tails that continue the outer segments' slopes to probability 0 and 1, clipped to
    the bounds. Copied from the Texas repository's src/i86/dists.py at cb2d06b."""
    levels = np.asarray(levels, dtype=float)
    xs = np.atleast_2d(np.asarray(xs, dtype=float))
    left = xs[:, 0] - (xs[:, 1] - xs[:, 0]) * levels[0] / (levels[1] - levels[0])
    right = xs[:, -1] + (xs[:, -1] - xs[:, -2]) * (1 - levels[-1]) / (levels[-1] - levels[-2])
    left = np.clip(left, lo, xs[:, 0])
    right = np.clip(right, xs[:, -1], hi)
    probs = np.concatenate([[0.0], levels, [1.0]])
    values = np.column_stack([left, xs, right])
    return probs, values


def quantity_mean(quantiles, lo: float = SENATE_BOUNDS[0], hi: float = SENATE_BOUNDS[1]) -> float:
    """The mean of that distribution: the paper's measure of a Talarico answer."""
    probs, values = quantity_knots(QUANTILES, [quantiles], lo, hi)
    v = values[0]
    return float(np.sum(np.diff(probs) * (v[:-1] + v[1:]) / 2.0))


def answer_value(question: str, value) -> float:
    """One context's answer to one question at one cell, in points: a probability times 100, or the
    mean of a Talarico distribution."""
    if question in BINARY:
        return float(value) * SCALE[question]
    if question in QUANTITY:
        return quantity_mean(value)
    raise KeyError(question)
