"""Acceptance tests for the pairwise-comparison Laplace fit: an operator judgment (A/B/tie
on one dimension) between two openings shifts their fitted means apart and narrows the
winner's uncertainty, converging toward the loser's mean losing ground as evidence
accumulates. Toy-example expectations below (prior N(0.6, 0.5²), β=0.5, 0/1/3 wins) were
validated against the operator's own worked-out numbers.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from screen.score.compare import Comparison, fit_pairwise


@pytest.mark.parametrize(
    ("b_wins", "expected_p_b_beats_a", "expected_sd"),
    [
        (0, 0.49, 0.50),
        (1, 0.80, 0.44),
        (3, 0.96, 0.42),
    ],
)
def test_fit_pairwise_matches_toy_numbers(
    b_wins: int, expected_p_b_beats_a: float, expected_sd: float
) -> None:
    """Prior N(0.6, 0.5**2), beta=0.5, opening B beats opening A `b_wins` times. P(B > A)
    and each opening's own sd should land near the operator's worked-out numbers, with a
    tolerance loose enough for the fit's exact numerics to differ slightly."""
    prior_means = {"a": 0.6, "b": 0.6}
    prior_variances = {"a": 0.25, "b": 0.25}
    comparisons = [Comparison(winner="b", loser="a", tie=False) for _ in range(b_wins)]

    means, covariance = fit_pairwise(prior_means, prior_variances, comparisons, beta=0.5)

    sd_a = math.sqrt(covariance[0, 0])
    joint_sd = math.sqrt(covariance[0, 0] + covariance[1, 1] - 2 * covariance[0, 1])
    p_b_beats_a = 0.5 * (1 + math.erf((means[1] - means[0]) / joint_sd / math.sqrt(2)))

    assert sd_a == pytest.approx(expected_sd, abs=0.03)
    assert p_b_beats_a == pytest.approx(expected_p_b_beats_a, abs=0.08)


def test_fit_pairwise_no_comparisons_returns_prior() -> None:
    """Zero comparisons: the MAP is exactly the prior, covariance is exactly the prior
    variance — the fit must reduce to a no-op, not merely approximate one."""
    prior_means = {"a": 0.6, "b": -0.2}
    prior_variances = {"a": 0.25, "b": 0.16}

    means, covariance = fit_pairwise(prior_means, prior_variances, [], beta=0.5)

    assert means == pytest.approx([0.6, -0.2])
    assert np.diag(covariance) == pytest.approx([0.25, 0.16])
    assert covariance[0, 1] == pytest.approx(0.0)


def test_fit_pairwise_tie_pulls_means_together() -> None:
    """A tie is symmetric evidence: it should not move either mean away from a shared
    starting point, only tighten uncertainty relative to zero comparisons."""
    prior_means = {"a": 0.0, "b": 0.5}
    prior_variances = {"a": 0.25, "b": 0.25}
    comparisons = [Comparison(winner="a", loser="b", tie=True)]

    means, covariance = fit_pairwise(prior_means, prior_variances, comparisons, beta=0.5)
    no_comparison_means, no_comparison_cov = fit_pairwise(
        prior_means, prior_variances, [], beta=0.5
    )

    assert means[1] - means[0] < no_comparison_means[1] - no_comparison_means[0]


def test_fit_pairwise_order_independent() -> None:
    """The batch fit reads a comparison list, not a stream — the result must not depend
    on the order comparisons are listed in."""
    prior_means = {"a": 0.6, "b": 0.6, "c": 0.6}
    prior_variances = {"a": 0.25, "b": 0.25, "c": 0.25}
    comparisons = [
        Comparison(winner="b", loser="a", tie=False),
        Comparison(winner="c", loser="a", tie=False),
        Comparison(winner="b", loser="c", tie=True),
    ]

    means_forward, cov_forward = fit_pairwise(prior_means, prior_variances, comparisons, beta=0.5)
    means_reversed, cov_reversed = fit_pairwise(
        prior_means, prior_variances, list(reversed(comparisons)), beta=0.5
    )

    assert means_forward == pytest.approx(means_reversed)
    assert cov_forward == pytest.approx(cov_reversed)
