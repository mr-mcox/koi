"""Tests for `pre_comparison_probability`: the logged P(A beats B) must come from
assertion priors alone, before any comparison data is consulted."""

from __future__ import annotations

import pytest

from screen.score.compare_probability import pre_comparison_probability


def test_identical_priors_are_fifty_fifty() -> None:
    assert pre_comparison_probability(0.0, 1.0, 0.0, 1.0) == pytest.approx(0.5)


def test_a_completely_above_b_is_one() -> None:
    assert pre_comparison_probability(0.6, 0.1, 0.0, 0.1) == pytest.approx(1.0)


def test_a_completely_below_b_is_zero() -> None:
    assert pre_comparison_probability(0.0, 0.1, 0.6, 0.1) == pytest.approx(0.0)


def test_overlap_with_a_higher_is_between_zero_and_one() -> None:
    # X_a ~ U(0.0, 1.0), X_b ~ U(-0.5, 0.5). P(a > b) = 7/8.
    assert pre_comparison_probability(0.5, 0.5, 0.0, 0.5) == pytest.approx(7.0 / 8.0)


def test_point_mass_against_uniform() -> None:
    assert pre_comparison_probability(0.5, 0.0, 0.0, 1.0) == pytest.approx(0.75)
    assert pre_comparison_probability(-0.5, 0.0, 0.0, 1.0) == pytest.approx(0.25)


def test_point_mass_at_uniform_boundary() -> None:
    assert pre_comparison_probability(-1.0, 0.0, 0.0, 1.0) == 0.0
    assert pre_comparison_probability(1.0, 0.0, 0.0, 1.0) == 1.0


def test_two_point_masses() -> None:
    assert pre_comparison_probability(0.1, 0.0, 0.0, 0.0) == 1.0
    assert pre_comparison_probability(0.0, 0.0, 0.0, 0.0) == 0.5
    assert pre_comparison_probability(-0.1, 0.0, 0.0, 0.0) == 0.0


def test_uniform_vs_point_mass_at_boundary() -> None:
    # B is a point mass at A's upper bound -> A is never strictly greater.
    assert pre_comparison_probability(0.0, 1.0, 1.0, 0.0) == 0.0
    # B is a point mass at A's lower bound -> A is always strictly greater.
    assert pre_comparison_probability(0.0, 1.0, -1.0, 0.0) == 1.0
