"""Tests for screen.score.bandit: aggregate remaining-uncertainty per opening, the
weighting signal for research-batch's per-turn draw."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from screen.score.bandit import aggregate_uncertainty, draw_opening
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.types import Assertion, Citation, Fit, Provenance, Target

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)

_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _assertion(target: Target, fit: Fit, provenance: Provenance = "model_proposed") -> Assertion:
    return Assertion(
        target=target,
        fit=fit,
        provenance=provenance,
        chunk="chunk",
        citations=[_CITATION],
        created_at=_NOW,
    )


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


def test_wide_high_weight_targets_outrank_narrow_low_weight_targets(config: ScoringConfig) -> None:
    """An opening with only wide-half-width, high-weight targets examined should score
    higher aggregate uncertainty than one with narrow-half-width, low-weight targets."""
    # "stretch" carries weight 3 in scoring.yaml; leaving it fully unexamined keeps its
    # half-width at the Uniform(-1, 1) maximum (1.0).
    wide_high_weight = [_assertion("domain", "Strong")]
    # "domain" carries weight 1; many ratified (heavily-weighted) assertions collapse its
    # half-width close to zero.
    narrow_low_weight = [_assertion("domain", "Strong", "ratified") for _ in range(20)]

    assert aggregate_uncertainty(wide_high_weight, config) > aggregate_uncertainty(
        narrow_low_weight, config
    )


def test_fully_examined_opening_has_lower_uncertainty_than_untouched_one(
    config: ScoringConfig,
) -> None:
    """An opening with no assertions at all (every target unexamined, half-width 1.0
    everywhere) has strictly higher aggregate uncertainty than one where every target has
    been heavily, consistently examined."""
    untouched: list[Assertion] = []
    all_targets = list(config.dimension_weights) + list(config.constraints)
    examined = [
        _assertion(target, "Strong", "ratified") for target in all_targets for _ in range(10)
    ]

    assert aggregate_uncertainty(untouched, config) > aggregate_uncertainty(examined, config)


def test_draw_opening_favors_higher_weight_over_many_seeded_draws() -> None:
    """Weighted random draw, not argmax: over many draws from one seeded generator, the
    opening with the larger weight wins more often than the one with the smaller weight,
    but the smaller-weight one still wins sometimes (bearing Agreed: no single opening's
    weight can reach certainty)."""
    rng = np.random.default_rng(0)
    counts = {"wide": 0, "narrow": 0}
    for _ in range(2000):
        drawn = draw_opening({"wide": 3.0, "narrow": 1.0}, rng)
        counts[drawn] += 1
    assert counts["wide"] > counts["narrow"]
    assert counts["narrow"] > 0


def test_draw_opening_is_deterministic_given_a_seeded_generator() -> None:
    """Two generators seeded identically produce the identical draw sequence — the batch's
    determinism-from-`config.seed` contract."""
    weights = {"a": 2.0, "b": 1.0, "c": 0.5}
    rng_a = np.random.default_rng(42)
    rng_b = np.random.default_rng(42)
    seq_a = [draw_opening(weights, rng_a) for _ in range(10)]
    seq_b = [draw_opening(weights, rng_b) for _ in range(10)]
    assert seq_a == seq_b
