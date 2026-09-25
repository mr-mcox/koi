"""Acceptance tests for the pool-scoped Scorer (docs/architecture/domain-model.md, Scorer
section). Runs `rank_pool` against synthetic assertions covering every scoring dimension —
chosen over reading real seed data so this suite doesn't depend on an
uncommitted, gitignored `data/` directory sticking around in its current shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from screen.score.loader import load_scoring_config
from screen.score.scorer import rank_pool
from screen.score.types import DimensionPosterior, PoolInput, ScoringConfig
from screen.types import Assertion, Citation, Fit, Provenance, Target

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)


def _assertion(target: Target, fit: Fit, provenance: Provenance = "model_proposed") -> Assertion:
    return Assertion(
        target=target,
        fit=fit,
        provenance=provenance,
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


# One assertion per scoring dimension, mixing `ratified` and `model_proposed` provenance
# so every target has counted (non-unexamined) evidence with realistic variance —
# a uniform-provenance fixture would understate the shrinkage the Scorer actually applies.
PARTIALLY_RESEARCHED = [
    _assertion("craft_direction", "Strong", "ratified"),
    _assertion("schematic", "Strong", "ratified"),
    _assertion("trajectory", "Strong", "ratified"),
    _assertion("mission", "Strong", "ratified"),
    _assertion("agentic", "Strong", "ratified"),
    _assertion("compensation", "Strong", "ratified"),
    _assertion("domain", "Strong", "ratified"),
    _assertion("location", "Strong"),
    _assertion("internal_culture", "Strong"),
    _assertion("extractive_business", "Strong"),
]


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


POORLY_RESEARCHED = [_assertion(a.target, "Poor", a.provenance) for a in PARTIALLY_RESEARCHED]


def test_rank_pool_orders_strong_opening_above_poor(config: ScoringConfig) -> None:
    """A pool-scoped rank: the well-regarded opening should rank ahead of the poorly
    regarded one on both the expected rank and `P(top K)` readouts."""
    strong = PoolInput(opening_id="strong", assertions=PARTIALLY_RESEARCHED)
    poor = PoolInput(opening_id="poor", assertions=POORLY_RESEARCHED)

    result = rank_pool([strong, poor], config, top_k=1)
    by_id = {r.opening_id: r for r in result.opening_ranks}

    assert by_id["strong"].expected_rank < by_id["poor"].expected_rank
    assert by_id["strong"].p_top_k > by_id["poor"].p_top_k


def test_rank_pool_independent_of_opening_order(config: ScoringConfig) -> None:
    strong = PoolInput(opening_id="strong", assertions=PARTIALLY_RESEARCHED)
    poor = PoolInput(opening_id="poor", assertions=POORLY_RESEARCHED)

    forward = rank_pool([strong, poor], config, top_k=1)
    backward = rank_pool([poor, strong], config, top_k=1)

    forward_by_id = {r.opening_id: r for r in forward.opening_ranks}
    backward_by_id = {r.opening_id: r for r in backward.opening_ranks}
    for opening_id in ("strong", "poor"):
        assert forward_by_id[opening_id].expected_rank == pytest.approx(
            backward_by_id[opening_id].expected_rank
        )
        assert forward_by_id[opening_id].p_top_k == pytest.approx(
            backward_by_id[opening_id].p_top_k
        )


def test_rank_pool_settledness_high_when_pool_is_separated(config: ScoringConfig) -> None:
    """A pool where one opening dominates the other on every target settles near K/K —
    the sampled top-K almost always matches the current top-K."""
    strong = PoolInput(opening_id="strong", assertions=PARTIALLY_RESEARCHED)
    poor = PoolInput(opening_id="poor", assertions=POORLY_RESEARCHED)

    result = rank_pool([strong, poor], config, top_k=1)

    assert result.settledness > 0.9


def test_rank_pool_kill_dimension_sinks_an_otherwise_best_opening(
    config: ScoringConfig,
) -> None:
    """A confident Poor on one high-weight dimension (location, relocation required with no
    flexibility language) drags `P(top K)` to ~0 even though every other dimension is
    Strong — the additive-weight replacement for the retired multiplicative constraint
    kill (constraints-and-rubric.md)."""
    killed_assertions = [a for a in PARTIALLY_RESEARCHED if a.target != "location"] + [
        _assertion("location", "Poor", "ratified")
    ]
    killed = PoolInput(opening_id="killed", assertions=killed_assertions)
    clean = PoolInput(opening_id="clean", assertions=PARTIALLY_RESEARCHED)
    result = rank_pool([killed, clean], config, top_k=1)
    by_id = {r.opening_id: r for r in result.opening_ranks}

    assert by_id["killed"].p_top_k < 0.1


def test_rank_pool_posterior_seam_reproduces_supplied_correlation(
    config: ScoringConfig,
) -> None:
    """With no comparisons a dimension draw is independent (diagonal covariance); this
    exercises the `DimensionPosterior` seam by supplying a fitted posterior directly."""

    a = PoolInput(opening_id="a", assertions=[])
    b = PoolInput(opening_id="b", assertions=[])
    correlation = 0.6
    posteriors = {
        "craft_direction": DimensionPosterior(
            opening_ids=["a", "b"],
            means=np.array([0.0, 0.0]),
            covariance=np.array([[1.0, correlation], [correlation, 1.0]]),
        )
    }

    result = rank_pool([a, b], config, top_k=1, posteriors=posteriors)

    craft_trace = result.dimension_trace["craft_direction"]
    sampled_correlation = np.corrcoef(craft_trace[0], craft_trace[1])[0, 1]
    assert sampled_correlation == pytest.approx(correlation, abs=0.05)


def test_rank_pool_posterior_ignores_openings_outside_the_current_pool(
    config: ScoringConfig,
) -> None:
    """A fitted posterior can cover an opening that has since left the pool (stage change,
    deletion) — its row must be skipped, not indexed into a pool array that no longer has
    a slot for it."""
    a = PoolInput(opening_id="a", assertions=[])
    posteriors = {
        "craft_direction": DimensionPosterior(
            opening_ids=["a", "departed"],
            means=np.array([0.0, 0.0]),
            covariance=np.array([[1.0, 0.0], [0.0, 1.0]]),
        )
    }

    result = rank_pool([a], config, top_k=1, posteriors=posteriors)

    assert result.opening_ids == ["a"]


def test_rank_pool_default_posterior_is_diagonal(config: ScoringConfig) -> None:
    """With no posterior supplied (no comparisons yet), two openings' dimension draws are
    independent — near-zero sampled correlation."""
    a = PoolInput(opening_id="a", assertions=[])
    b = PoolInput(opening_id="b", assertions=[])

    result = rank_pool([a, b], config, top_k=1)

    craft_trace = result.dimension_trace["craft_direction"]
    sampled_correlation = np.corrcoef(craft_trace[0], craft_trace[1])[0, 1]
    assert abs(sampled_correlation) < 0.05


def test_rank_pool_posterior_mean_shift_moves_rank_order(config: ScoringConfig) -> None:
    """The fitted mean is what a comparison is *for*: two openings with identical
    assertions (equal priors, so assertion evidence alone can't separate them) must swap
    rank order once a `DimensionPosterior` gives one a higher fitted mean on a
    heavily-weighted dimension."""
    tied = [_assertion("craft_direction", "Strong", "ratified")]
    a = PoolInput(opening_id="a", assertions=tied)
    b = PoolInput(opening_id="b", assertions=tied)

    baseline = rank_pool([a, b], config, top_k=1)
    by_id = {r.opening_id: r for r in baseline.opening_ranks}
    assert by_id["a"].expected_rank == pytest.approx(by_id["b"].expected_rank, abs=0.01)

    posteriors = {
        "craft_direction": DimensionPosterior(
            opening_ids=["a", "b"],
            means=np.array([-0.9, 0.9]),
            covariance=np.diag([0.05, 0.05]),
        )
    }
    result = rank_pool([a, b], config, top_k=1, posteriors=posteriors)
    by_id = {r.opening_id: r for r in result.opening_ranks}

    assert by_id["b"].expected_rank < by_id["a"].expected_rank
