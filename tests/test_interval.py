"""Tests for screen.score.interval: the (low, median, high) display statistics for one
opening's `overall` trace."""

from __future__ import annotations

import numpy as np
import pytest

from screen.score.interval import credible_interval
from screen.score.types import ScoreResult


def _result(trace: list[float]) -> ScoreResult:
    return ScoreResult(trace=np.array(trace), bar=0.60, ceiling=1.0)


def test_credible_interval_brackets_median_for_spread_trace() -> None:
    """A trace with real spread produces low < median < high."""
    result = _result([0.1, 0.3, 0.5, 0.7, 0.9] * 20)

    low, median, high = credible_interval(result)

    assert low < median < high


def test_credible_interval_collapses_for_degenerate_trace() -> None:
    """Every draw identical means no uncertainty: low == median == high."""
    result = _result([0.5] * 10)

    low, median, high = credible_interval(result)

    assert low == pytest.approx(0.5)
    assert median == pytest.approx(0.5)
    assert high == pytest.approx(0.5)


def test_credible_interval_uses_q10_q50_q90_of_the_trace() -> None:
    """The interval is the trace's own 10th/50th/90th percentile, not a derived formula —
    matches `np.quantile` directly so there's no second definition to drift out of sync."""
    trace = list(np.linspace(0.0, 1.0, 101))
    result = _result(trace)

    low, median, high = credible_interval(result)

    assert low == pytest.approx(np.quantile(trace, 0.10))
    assert median == pytest.approx(np.quantile(trace, 0.50))
    assert high == pytest.approx(np.quantile(trace, 0.90))
