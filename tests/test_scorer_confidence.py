"""Tests for `stats_for_target`'s confidence-scaled variance (docs/architecture/
domain-model.md Wall 1: confidence scales variance only, never the mean/fit).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from screen.score import scorer
from screen.score.loader import load_scoring_config
from screen.score.scorer import stats_for_target
from screen.score.types import ScoringConfig
from screen.types import Assertion, Citation

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)


def _assertion(confidence: float | None) -> Assertion:
    return Assertion(
        target="craft_direction",
        fit="Strong",
        provenance="model_proposed",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
        confidence=confidence,
    )


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


def test_confidence_widens_half_width_without_moving_mean(config: ScoringConfig) -> None:
    """Two assertions with identical `fit` but different confidence must produce the
    same mean and different `half_width` (bearing Done When #3)."""
    high_conf = stats_for_target([_assertion(0.95)], config, "craft_direction")
    low_conf = stats_for_target([_assertion(0.3)], config, "craft_direction")

    assert high_conf.mean == pytest.approx(low_conf.mean)
    assert low_conf.half_width > high_conf.half_width


def test_missing_confidence_defaults_to_no_widening(config: ScoringConfig) -> None:
    """`confidence=None` (legacy/pre-migration rows) behaves as full confidence (1.0) —
    same half_width as an explicit 1.0, strictly narrower than a low-confidence case."""
    unset = stats_for_target([_assertion(None)], config, "craft_direction")
    explicit_full = stats_for_target([_assertion(1.0)], config, "craft_direction")
    low_conf = stats_for_target([_assertion(0.3)], config, "craft_direction")

    assert unset.half_width == pytest.approx(explicit_full.half_width)
    assert unset.half_width < low_conf.half_width


def test_confidence_floors_at_point_three(config: ScoringConfig) -> None:
    """Below the 0.3 floor, widening plateaus rather than cliffing further — confidence
    0.1 and 0.3 must produce the same half_width."""
    floored = stats_for_target([_assertion(0.1)], config, "craft_direction")
    at_floor = stats_for_target([_assertion(0.3)], config, "craft_direction")

    assert floored.half_width == pytest.approx(at_floor.half_width)


def test_stats_for_target_never_multiplies_fit_value_by_confidence(config: ScoringConfig) -> None:
    """Structural guard for Wall 1: the source of `stats_for_target` must never multiply
    a FIT_VALUES lookup by a confidence term directly — confidence may only reach the
    half_width/variance computation, never `weighted_sum` or `mean`. A regression
    reintroducing `weighted_sum *= confidence` or `FIT_VALUES[fit] * conf` should fail
    this test, not just silently change scores."""
    source = inspect.getsource(scorer.stats_for_target)
    mean_section, _, variance_section = source.partition("mean = weighted_sum / total_n")

    assert "a.confidence" not in mean_section, (
        "`a.confidence` must not be read before the mean is computed — it may only scale "
        "half_width/variance, per Wall 1 (domain-model.md)."
    )
    assert "FIT_VALUES" not in variance_section, (
        "`FIT_VALUES` must not be referenced again after the mean is computed — confidence "
        "scaling must operate on half_width only, never re-touch the fit value."
    )
