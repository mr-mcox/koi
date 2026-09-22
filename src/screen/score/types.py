"""Pure data shapes for the Scorer (docs/architecture/domain-model.md, Scorer section).
`PoolScoreResult` stores the pool's joint Monte Carlo trace; rank, `p_top_k`, and
settledness are computed from it on read, never stored fields of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from screen.types import Assertion, Fit, Provenance

FIT_VALUES: dict[Fit, float] = {"Poor": -1.0, "Mixed": 0.0, "Strong": 1.0}


@dataclass(frozen=True)
class ScoringConfig:
    """Everything the Scorer needs, pre-loaded. No I/O happens past this point —
    `screen.score.loader` is where `rubric.yaml`/`scoring.yaml` get read."""

    seed: int
    samples: int
    provenance_weight: dict[Provenance, float]
    dimension_weights: dict[str, int]
    top_k: int
    research_target_action_cap: int
    comparison_beta: float
    comparison_jitter_sigma: float

    @property
    def total_weight(self) -> int:
        return sum(self.dimension_weights.values())


@dataclass(frozen=True)
class PoolInput:
    """One opening's evidence for a pool-scored ranking: its assertions and any per-assertion
    rulings. `PoolInput` does not carry `dimension_rulings` — a per-target pin has no place
    in the pool-scored model."""

    opening_id: str
    assertions: list[Assertion]
    rulings: dict[str, Fit] | None = None


@dataclass(frozen=True)
class DimensionPosterior:
    """One dimension's joint posterior over a set of openings, produced by a batch
    pairwise fit (`screen.score.compare.fit_pairwise`).

    `opening_ids` gives `means`/`covariance`'s row order. For covered openings, this
    posterior replaces the independent assertion-derived prior entirely: a comparison
    shifts the mean, not just correlation. Openings not in `opening_ids` keep their
    ordinary assertion-derived prior for this dimension."""

    opening_ids: list[str]
    means: np.ndarray
    covariance: np.ndarray


@dataclass(frozen=True)
class OpeningRank:
    """One opening's rank readouts, derived from `PoolScoreResult.trace` on read: `1` is
    best. `p_top_k` is the fraction of samples landing at rank `<= top_k`; `rank_q10/50/90`
    are quantiles of the sampled rank distribution, not the overall-score distribution."""

    opening_id: str
    expected_rank: float
    p_top_k: float
    rank_q10: float
    rank_q50: float
    rank_q90: float


@dataclass(frozen=True)
class PoolScoreResult:
    """One Monte Carlo run of the whole screening pool: `trace` is openings x samples of
    `overall`, sampled jointly so cross-opening correlation is possible. `opening_ranks`
    and `settledness` are computed from `trace` on read — rank is a property of the joint
    draw, never a per-opening scalar stored on its own."""

    opening_ids: list[str]
    trace: np.ndarray = field(compare=False, repr=False)
    dimension_trace: dict[str, np.ndarray] = field(compare=False, repr=False)
    top_k: int
    opening_ranks: list[OpeningRank]
    settledness: float
