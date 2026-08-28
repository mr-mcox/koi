"""Unit tests for `screen.api.scoring.score_opening` — pure, no database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from screen.api.scoring import score_opening
from screen.score.band import band_for
from screen.score.loader import load_scoring_config
from screen.score.scorer import resolve_favourably, score
from screen.score.types import ScoringConfig
from screen.types import Assertion, Citation, Fit, Target

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)


def _assertion(target: Target, fit: Fit) -> Assertion:
    return Assertion(
        target=target,
        fit=fit,
        provenance="model_proposed",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


@pytest.fixture(scope="module")
def config() -> ScoringConfig:
    return load_scoring_config()


def test_score_opening_matches_direct_scorer_calls(config: ScoringConfig) -> None:
    """`score_opening`'s standing/reach/band must equal calling `score`/
    `resolve_favourably`/`band_for` directly with the same config — this module
    is a fixed recipe, not a second computation of the same numbers."""
    assertions = [_assertion("stretch", "Strong"), _assertion("location", "Strong")]

    result = score_opening(assertions, config)

    expected_standing = score(assertions, config)
    expected_reach = score(resolve_favourably(assertions, config), config)
    expected_band = band_for(expected_standing, expected_reach, config.bands)
    assert result.standing == pytest.approx(expected_standing.standing)
    assert result.reach == pytest.approx(expected_reach.standing)
    assert result.band == expected_band
    assert result.ceiling == pytest.approx(expected_standing.ceiling)
    assert result.unreachable == expected_standing.unreachable


def test_score_opening_handles_empty_assertions(config: ScoringConfig) -> None:
    """An opening with zero assertions (transcript only, nothing extracted yet)
    must score, not raise — every target enters at its unexamined prior."""
    result = score_opening([], config)
    assert 0.0 <= result.standing <= 1.0
    assert 0.0 <= result.reach <= 1.0
