"""Batch Laplace fit for pairwise dimension comparisons. Pure `(priors, comparisons, beta)
-> (means, covariance)` — no I/O, mirroring `scorer.py`. `screen.api.scoring` turns this
output into the `DimensionPosterior` `rank_pool` consumes; this module never touches
`rank_pool` itself.

Thurstone/probit model: a win is `Phi((theta_win - theta_lose) / beta)`, a tie is
`sqrt(Phi(d/beta) * Phi(-d/beta))`. The MAP is found by Newton's method against the
log-posterior (Gaussian prior + comparison log-likelihoods); the negative Hessian's
inverse at the MAP is the returned covariance. numpy/`math.erf` only — no scipy dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from screen.score.types import DimensionPosterior


@dataclass(frozen=True)
class Comparison:
    """One operator judgment on a single dimension between two openings, identified by
    the same keys used in `prior_means`/`prior_variances`. `tie=True` ignores which side is
    `winner`/`loser` — the likelihood term is symmetric either way."""

    winner: str
    loser: str
    tie: bool = False


COMPANY_LEVEL_TARGETS = frozenset({"mission", "trajectory", "agentic", "domain"})
"""Dimensions scoped to the Company, not the Opening. Two openings at the same company
auto-tie on these absent an explicit comparison — they share the same evidence, so an
unexamined difference isn't real signal."""


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class _Term:
    """One signed likelihood term: `sign=+1` credits `winner`, `sign=-1` credits `loser`,
    `weight` is 1 for a clean win's single term or 0.5 for each of a tie's two terms."""

    winner: int
    loser: int
    sign: float
    weight: float


def _accumulate_term(
    grad: np.ndarray, hessian: np.ndarray, term: _Term, diff: float, beta: float
) -> None:
    """One term's contribution to the gradient and Hessian of the log-posterior, at the
    current `diff = theta[winner] - theta[loser]`."""
    z = term.sign * diff / beta
    ratio = _pdf(z) / _cdf(z)
    grad_term = term.weight * term.sign / beta * ratio
    hess_term = term.weight * (-z * ratio - ratio * ratio) / (beta * beta)
    grad[term.winner] += grad_term
    grad[term.loser] -= grad_term
    hessian[term.winner, term.winner] += hess_term
    hessian[term.loser, term.loser] += hess_term
    hessian[term.winner, term.loser] -= hess_term
    hessian[term.loser, term.winner] -= hess_term


def _step(
    theta: np.ndarray,
    prior_means: np.ndarray,
    prior_variances: np.ndarray,
    indexed: list[tuple[int, int, bool]],
    beta: float,
) -> tuple[np.ndarray, np.ndarray]:
    """One Newton step's gradient and Hessian of the log-posterior at `theta`: the
    Gaussian prior term plus every comparison's likelihood term, summed — the result
    depends only on the term set, never the order comparisons were listed in."""
    grad = -(theta - prior_means) / prior_variances
    hessian = np.diag(-1.0 / prior_variances)
    for winner, loser, tie in indexed:
        diff = float(theta[winner] - theta[loser])
        if tie:
            _accumulate_term(grad, hessian, _Term(winner, loser, 1.0, 0.5), diff, beta)
            _accumulate_term(grad, hessian, _Term(winner, loser, -1.0, 0.5), diff, beta)
        else:
            _accumulate_term(grad, hessian, _Term(winner, loser, 1.0, 1.0), diff, beta)
    return grad, hessian


def fit_pairwise(
    prior_means: dict[str, float],
    prior_variances: dict[str, float],
    comparisons: list[Comparison],
    beta: float,
    iterations: int = 50,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit one dimension's latent values jointly across every opening named in
    `prior_means`. Returns `(means, covariance)` in `prior_means`' key order — the shape
    `screen.api.scoring` wraps into a `DimensionPosterior`. Zero comparisons returns the
    prior unchanged."""
    keys = list(prior_means)
    index = {key: i for i, key in enumerate(keys)}
    means = np.array([prior_means[key] for key in keys], dtype=float)
    variances = np.array([prior_variances[key] for key in keys], dtype=float)
    indexed = [(index[c.winner], index[c.loser], c.tie) for c in comparisons]

    theta = means.copy()
    hessian = np.diag(-1.0 / variances)
    for _ in range(iterations if indexed else 0):
        grad, hessian = _step(theta, means, variances, indexed, beta)
        theta = theta - np.linalg.solve(hessian, grad)

    covariance = np.diag(variances) if not indexed else -np.linalg.inv(hessian)
    return theta, covariance


def _auto_tie_comparisons(
    opening_ids: list[str], companies_by_opening: dict[str, str]
) -> list[Comparison]:
    """Every same-company pair among `opening_ids` gets an implicit tie — generated, never
    stored as an operator comparison or logged for calibration."""
    by_company: dict[str, list[str]] = {}
    for oid in opening_ids:
        by_company.setdefault(companies_by_opening[oid], []).append(oid)
    return [
        Comparison(winner=ids[i], loser=ids[j], tie=True)
        for ids in by_company.values()
        for i in range(len(ids))
        for j in range(i + 1, len(ids))
    ]


def dimension_posteriors(
    prior_means: dict[str, dict[str, float]],
    prior_variances: dict[str, dict[str, float]],
    companies_by_opening: dict[str, str],
    comparisons_by_target: dict[str, list[Comparison]],
    beta: float,
) -> dict[str, DimensionPosterior]:
    """Fit every dimension that has either a recorded comparison or a same-company pair
    needing an auto-tie. A dimension with
    neither is left out entirely — `rank_pool` falls back to its ordinary assertion-derived
    prior for any dimension missing from the returned dict. Comparisons naming an opening
    outside the current pool (e.g. moved out of screening since the comparison was made)
    are dropped rather than fed to `fit_pairwise`, which indexes strictly by `prior_means`."""
    posteriors: dict[str, DimensionPosterior] = {}
    for target, means in prior_means.items():
        opening_ids = list(means)
        valid_ids = set(opening_ids)
        comparisons = [
            c
            for c in comparisons_by_target.get(target, [])
            if c.winner in valid_ids and c.loser in valid_ids
        ]
        if target in COMPANY_LEVEL_TARGETS:
            comparisons += _auto_tie_comparisons(opening_ids, companies_by_opening)
        if not comparisons:
            continue
        fitted_means, covariance = fit_pairwise(means, prior_variances[target], comparisons, beta)
        posteriors[target] = DimensionPosterior(
            opening_ids=opening_ids, means=fitted_means, covariance=covariance
        )
    return posteriors
