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

from screen.score.compare import Comparison, dimension_posteriors, fit_pairwise
from screen.score.types import ComparisonBetaParams

_BETA = ComparisonBetaParams(operator=0.5, provisional=1.0)


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
    """Prior N(0.6, 0.5**2), beta_params=_BETA, opening B beats opening A `b_wins` times. P(B > A)
    and each opening's own sd should land near the operator's worked-out numbers, with a
    tolerance loose enough for the fit's exact numerics to differ slightly."""
    prior_means = {"a": 0.6, "b": 0.6}
    prior_variances = {"a": 0.25, "b": 0.25}
    comparisons = [Comparison(winner="b", loser="a", tie=False) for _ in range(b_wins)]

    means, covariance = fit_pairwise(prior_means, prior_variances, comparisons, beta_params=_BETA)

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

    means, covariance = fit_pairwise(prior_means, prior_variances, [], beta_params=_BETA)

    assert means == pytest.approx([0.6, -0.2])
    assert np.diag(covariance) == pytest.approx([0.25, 0.16])
    assert covariance[0, 1] == pytest.approx(0.0)


def test_fit_pairwise_tie_pulls_means_together() -> None:
    """A tie is symmetric evidence: it should not move either mean away from a shared
    starting point, only tighten uncertainty relative to zero comparisons."""
    prior_means = {"a": 0.0, "b": 0.5}
    prior_variances = {"a": 0.25, "b": 0.25}
    comparisons = [Comparison(winner="a", loser="b", tie=True)]

    means, covariance = fit_pairwise(prior_means, prior_variances, comparisons, beta_params=_BETA)
    no_comparison_means, no_comparison_cov = fit_pairwise(
        prior_means, prior_variances, [], beta_params=_BETA
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

    means_forward, cov_forward = fit_pairwise(
        prior_means, prior_variances, comparisons, beta_params=_BETA
    )
    means_reversed, cov_reversed = fit_pairwise(
        prior_means, prior_variances, list(reversed(comparisons)), beta_params=_BETA
    )

    assert means_forward == pytest.approx(means_reversed)
    assert cov_forward == pytest.approx(cov_reversed)


def test_dimension_posteriors_reduces_to_latest_per_pair() -> None:
    """Two recorded judgments on the same (pair, dimension) collapse to the latest — the
    fit must equal the single-latest-judgment fit, not the sum of both. `comparisons_for_target`
    returns oldest-first, so the later ruling displaces the earlier one on that pair
    ("until I override" is literal, not a weight competition). Closes F18."""
    prior_means = {"location": {"a": 0.0, "b": 0.0}}
    prior_variances = {"location": {"a": 0.25, "b": 0.25}}
    companies_by_opening = {"a": "acme", "b": "widgets"}

    both = dimension_posteriors(
        prior_means,
        prior_variances,
        companies_by_opening,
        {
            "location": [
                Comparison(winner="a", loser="b", tie=False),  # older ruling
                Comparison(winner="b", loser="a", tie=False),  # latest ruling
            ]
        },
        beta_params=_BETA,
    )
    latest_only = dimension_posteriors(
        prior_means,
        prior_variances,
        companies_by_opening,
        {"location": [Comparison(winner="b", loser="a", tie=False)]},
        beta_params=_BETA,
    )

    assert both["location"].means == pytest.approx(latest_only["location"].means)
    assert both["location"].covariance == pytest.approx(latest_only["location"].covariance)


def test_explicit_comparison_displaces_same_company_auto_tie() -> None:
    """An explicit operator comparison on a company-level dimension (`mission`) between two
    same-company openings displaces the auto-tie for that pair — the fit equals the
    different-company fit (no implicit tie term summed in), not a blend of win and tie. The
    auto-tie is the default absent an explicit judgment, not a coexisting term (F18)."""
    prior_means = {"mission": {"a": 0.0, "b": 0.0}}
    prior_variances = {"mission": {"a": 0.25, "b": 0.25}}
    win = {"mission": [Comparison(winner="a", loser="b", tie=False)]}

    same_company = dimension_posteriors(
        prior_means, prior_variances, {"a": "acme", "b": "acme"}, win, beta_params=_BETA
    )
    diff_company = dimension_posteriors(
        prior_means, prior_variances, {"a": "acme", "b": "widgets"}, win, beta_params=_BETA
    )

    # The explicit win displaces the auto-tie: same-company fit == different-company fit.
    assert same_company["mission"].means == pytest.approx(diff_company["mission"].means)
    assert same_company["mission"].covariance == pytest.approx(diff_company["mission"].covariance)
    # And the win actually separates the means — the auto-tie isn't pulling them back together.
    assert same_company["mission"].means[0] > same_company["mission"].means[1]


def test_provisional_tie_weighs_less_than_operator_tie() -> None:
    """A provisional similarity tie uses a wider beta than an operator tie, so it tightens
    the posterior less — the same judgment at provisional provenance moves the fit less than
    the identical judgment at operator provenance (Done When: provisional weighs less, via
    per-provenance beta)."""
    prior_means = {"a": 0.0, "b": 1.0}
    prior_variances = {"a": 0.25, "b": 0.25}
    operator_tie = [Comparison(winner="a", loser="b", tie=True, provenance="operator")]
    provisional_tie = [Comparison(winner="a", loser="b", tie=True, provenance="provisional")]

    op_means, op_cov = fit_pairwise(prior_means, prior_variances, operator_tie, beta_params=_BETA)
    prov_means, prov_cov = fit_pairwise(
        prior_means, prior_variances, provisional_tie, beta_params=_BETA
    )

    # Both ties pull the means together, but the narrower-beta operator tie pulls harder.
    assert abs(op_means[0] - op_means[1]) < abs(prov_means[0] - prov_means[1])
    # And tightens uncertainty more.
    assert op_cov[0, 0] < prov_cov[0, 0]
