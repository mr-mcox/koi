"""Pure Scorer: pool-scoped ranking over a screening pool's assertions (see
domain-model.md's Scorer section: "the Scorer" is defined as this pure function, distinct
from config loading; `screen.score.loader` does the I/O).

Implements S1/S2/S3/S8 (docs/architecture/decisions.md): an unexamined target is a wide
Uniform(-1, +1); a target with counted evidence shrinks toward its sample mean; provenance
sets the effective weight of each piece of evidence, in place of the prototype's binary
Medium/High confidence gate. Every scored target, including `location`, `internal_culture`,
and `extractive_business`, is a dimension in the same weighted rollup — there is no
separate constraint or multiplicative scoring path.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from screen.score.types import (
    FIT_VALUES,
    DimensionPosterior,
    OpeningRank,
    PoolInput,
    PoolScoreResult,
    ScoringConfig,
)
from screen.types import Assertion, Fit


@dataclass(frozen=True)
class TargetStats:
    """Shrunk mean/half-width for one dimension, computed from its assertions'
    provenance-weighted fit values. `n = 0` (no counted weight) is the unexamined
    case — `mean = 0`, `half_width = 1`, i.e. Uniform(-1, +1), from the formula itself rather
    than a special-cased branch."""

    n: float
    mean: float
    half_width: float


def stats_for_target(
    assertions: list[Assertion],
    config: ScoringConfig,
    target: str,
    rulings: dict[str, Fit] | None = None,
) -> TargetStats:
    """Shrinks a target's assertions toward the unexamined prior (weight 1, mean 0)."""
    weighted_sum = 0.0
    total_n = 1.0
    new_n = 0.0
    for a in assertions:
        if a.target != target:
            continue
        weight = config.provenance_weight[a.provenance]
        fit = rulings[a.id] if rulings is not None and a.id in rulings else a.fit
        weighted_sum += weight * FIT_VALUES[fit]
        total_n += weight
        new_n += weight
    mean = weighted_sum / total_n
    return TargetStats(n=new_n, mean=mean, half_width=1.0 / math.sqrt(total_n))


def _sample_dimension_gaussian(
    rng: np.random.Generator, means: np.ndarray, half_widths: np.ndarray, samples: int
) -> np.ndarray:
    """Independent per-opening Gaussian draws, variance-matched to the Uniform(-hw, +hw) the
    per-opening Scorer used: `Var[Uniform(-hw, hw)] = hw^2 / 3`, so `std = hw / sqrt(3)`.
    Shape (n_openings, samples)."""
    stds = half_widths / math.sqrt(3.0)
    return rng.normal(means[:, None], stds[:, None], size=(len(means), samples))


def _sample_dimension_posterior(
    rng: np.random.Generator, posterior_means: np.ndarray, covariance: np.ndarray, samples: int
) -> np.ndarray:
    """Jointly-correlated per-opening Gaussian draws from a fitted `DimensionPosterior`.
    Shape (n_openings, samples)."""
    return rng.multivariate_normal(posterior_means, covariance, size=samples).T


def _sample_dimension(
    rng: np.random.Generator,
    opening_ids: list[str],
    stats: dict[str, TargetStats],
    posterior: DimensionPosterior | None,
    samples: int,
) -> np.ndarray:
    """One dimension's joint draw across the whole pool. Openings named in `posterior`
    draw jointly from its fitted mean/covariance; every other opening draws independently
    from its own assertion-derived stats. An opening no comparison has touched keeps
    exactly its prior."""
    draw = np.empty((len(opening_ids), samples))
    covered = set(posterior.opening_ids) if posterior is not None else set()
    uncovered = [oid for oid in opening_ids if oid not in covered]
    if uncovered:
        means = np.array([stats[oid].mean for oid in uncovered])
        half_widths = np.array([stats[oid].half_width for oid in uncovered])
        uncovered_draw = _sample_dimension_gaussian(rng, means, half_widths, samples)
        for row, oid in zip(uncovered_draw, uncovered, strict=True):
            draw[opening_ids.index(oid)] = row
    if posterior is not None:
        posterior_draw = _sample_dimension_posterior(
            rng, posterior.means, posterior.covariance, samples
        )
        for row, oid in zip(posterior_draw, posterior.opening_ids, strict=True):
            if oid in opening_ids:
                draw[opening_ids.index(oid)] = row
    return draw


def _opening_id_rank_key(opening_id: str) -> int:
    """A stable, order-independent tiebreak: two openings whose sampled `overall` and
    deterministic quality both tie (e.g. two unexamined openings) still rank consistently
    regardless of the order they were passed in."""
    return int.from_bytes(hashlib.sha256(opening_id.encode()).digest()[:8], "big")


def _deterministic_quality(
    dim_stats: dict[str, dict[str, TargetStats]],
    config: ScoringConfig,
    opening_id: str,
) -> float:
    """A tiebreak key only — the mean-weighted quality a sample-free estimate would give this
    opening. Deterministic given the inputs, so it never reintroduces order-dependence."""
    weighted = sum(
        weight * dim_stats[slug][opening_id].mean
        for slug, weight in config.dimension_weights.items()
    )
    return min(max((weighted / config.total_weight + 1.0) / 2.0, 0.0), 1.0)


def rank_pool(
    pool: list[PoolInput],
    config: ScoringConfig,
    *,
    top_k: int | None = None,
    posteriors: dict[str, DimensionPosterior] | None = None,
) -> PoolScoreResult:
    """Score the whole screening pool jointly: one `overall` trace per opening, sampled
    together so a dimension's fitted cross-opening posterior is possible. Rank is a
    property of the joint draw — computed here from the trace, on read, never a
    per-opening scalar. `top_k` defaults to `config.top_k`; overridable for tests against
    small synthetic pools."""
    top_k = config.top_k if top_k is None else top_k
    rng = np.random.default_rng(config.seed)
    samples = config.samples
    opening_ids = [p.opening_id for p in pool]
    n = len(opening_ids)
    dim_stats = {
        slug: {p.opening_id: stats_for_target(p.assertions, config, slug, p.rulings) for p in pool}
        for slug in config.dimension_weights
    }
    weighted = np.zeros((n, samples))
    dimension_trace: dict[str, np.ndarray] = {}
    for slug, weight in config.dimension_weights.items():
        posterior = posteriors.get(slug) if posteriors is not None else None
        draw = _sample_dimension(rng, opening_ids, dim_stats[slug], posterior, samples)
        dimension_trace[slug] = draw
        weighted += weight * draw
    overall = np.clip((weighted / config.total_weight + 1.0) / 2.0, 0.0, 1.0)

    deterministic_quality = np.array(
        [_deterministic_quality(dim_stats, config, oid) for oid in opening_ids]
    )
    tiebreak_keys = np.array([_opening_id_rank_key(oid) for oid in opening_ids], dtype=np.float64)
    tiebreak_keys /= 2.0**64  # normalize into [0, 1)

    # Rank each sample (column) independently, vectorized: `overall` decides it whenever
    # samples differ; `deterministic_quality` then `opening_id`'s hash break exact ties (e.g.
    # two unexamined openings, or two killed by the same dimension) the same way regardless
    # of the order openings were passed in — neither ever comes from the trace itself.
    key = overall + deterministic_quality[:, None] * 1e-9 + tiebreak_keys[:, None] * 1e-18
    order = np.argsort(-key, axis=0)
    ranks = np.empty_like(order)
    np.put_along_axis(ranks, order, np.arange(1, n + 1)[:, None], axis=0)
    opening_ranks = [
        OpeningRank(
            opening_id=oid,
            expected_rank=float(np.mean(ranks[i])),
            p_top_k=float(np.mean(ranks[i] <= top_k)),
            rank_q10=float(np.quantile(ranks[i], 0.10)),
            rank_q50=float(np.quantile(ranks[i], 0.50)),
            rank_q90=float(np.quantile(ranks[i], 0.90)),
        )
        for i, oid in enumerate(opening_ids)
    ]

    current_top_k_indices = [
        opening_ids.index(r.opening_id)
        for r in sorted(opening_ranks, key=lambda r: (-r.p_top_k, r.expected_rank, r.opening_id))[
            :top_k
        ]
    ]
    if current_top_k_indices:
        sampled_top_k = ranks <= top_k
        overlap = sampled_top_k[current_top_k_indices, :].sum(axis=0)
        settledness = float(np.mean(overlap)) / len(current_top_k_indices)
    else:
        settledness = 1.0
    return PoolScoreResult(
        opening_ids=opening_ids,
        trace=overall,
        dimension_trace=dimension_trace,
        top_k=top_k,
        opening_ranks=opening_ranks,
        settledness=settledness,
    )
