"""Tests for screen.score.boundary: P(rank crosses K) via K-th-trace comparison."""

from __future__ import annotations

import numpy as np
import pytest

from screen.score.boundary import crossing_probability
from screen.score.types import ScoreResult


def _result(trace: list[float]) -> ScoreResult:
    return ScoreResult(trace=np.array(trace), bar=0.60, ceiling=1.0)


def test_crossing_probability_is_zero_for_disjoint_lower_trace() -> None:
    """Every sample of this opening's trace is below every sample of the K-th
    opening's trace: it never crosses."""
    below = _result([0.1, 0.2, 0.3])
    kth = _result([0.9, 0.9, 0.9])
    assert crossing_probability(below, kth) == 0.0


def test_crossing_probability_is_one_for_disjoint_higher_trace() -> None:
    """Every sample of this opening's trace exceeds the K-th opening's trace: it
    always crosses."""
    above = _result([0.9, 0.9, 0.9])
    kth = _result([0.1, 0.2, 0.3])
    assert crossing_probability(above, kth) == 1.0


def test_crossing_probability_is_mid_range_for_overlapping_traces() -> None:
    """Overlapping ranges give a fraction strictly between 0 and 1, elementwise."""
    opening = _result([0.1, 0.5, 0.9])
    kth = _result([0.4, 0.4, 0.4])
    # exceeds kth on 2 of 3 elementwise draws: [0.5, 0.9] > 0.4
    assert crossing_probability(opening, kth) == pytest.approx(2 / 3)


def test_crossing_probability_requires_equal_length_traces() -> None:
    """Comparing traces from different sample counts would silently truncate under
    `np.mean` broadcasting; a mismatch is a caller error (traces from different
    configs), not a case to accommodate."""
    opening = _result([0.1, 0.2])
    kth = _result([0.4, 0.4, 0.4])
    with pytest.raises(ValueError):
        crossing_probability(opening, kth)
