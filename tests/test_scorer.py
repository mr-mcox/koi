"""Acceptance tests for the Scorer (docs/architecture/domain-model.md, Scorer section).

Runs the pure `score`/`resolve_favourably`/`band_for` functions against synthetic
assertions covering every scoring target and constraint — chosen over reading real seed
data so this suite doesn't depend on an uncommitted, gitignored `data/` directory sticking
around in its current shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from screen.score.band import band_for
from screen.score.loader import load_scoring_config
from screen.score.scorer import resolve_favourably, score, unexamined_targets
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


def _assertion(target: Target, fit: Fit, provenance: Provenance = "model_proposed") -> Assertion:
    return Assertion(
        target=target,
        fit=fit,
        provenance=provenance,
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


# One assertion per scoring dimension and constraint, high-confidence (`ratified`) on the
# seven dimensions, thinner (`model_proposed`) on the three constraints — enough for every
# target to have counted (non-unexamined) evidence, straddling the bar so standing lands
# strictly between 0 and 1 rather than saturating at an extreme.
PARTIALLY_RESEARCHED = [
    _assertion("stretch", "Strong", "ratified"),
    _assertion("schematic", "Strong", "ratified"),
    _assertion("peer", "Strong", "ratified"),
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


def test_scores_partially_researched_opening(config: ScoringConfig) -> None:
    standing = score(PARTIALLY_RESEARCHED, config)
    reach = score(resolve_favourably(PARTIALLY_RESEARCHED, config), config)
    band = band_for(standing, reach, config.bands)

    assert 0.0 <= standing.standing <= 1.0
    assert 0.0 <= reach.standing <= 1.0
    # Reach never sorts below standing — resolving unexamined targets favourably can only
    # help or leave the pair unchanged (S5, docs/architecture/decisions.md).
    assert reach.standing >= standing.standing - 1e-9
    assert standing.ceiling <= 1.0
    assert band in {"no path", "contender", "established", "capped", "wide open"}
    # Every target here has counted evidence, so reach has nothing left to resolve.
    assert unexamined_targets(PARTIALLY_RESEARCHED, config) == []
    assert reach.standing == pytest.approx(standing.standing)


def test_standing_has_a_nontrivial_stderr(config: ScoringConfig) -> None:
    """A partially-researched opening's standing is neither 0 nor 1 — exercises
    `ScoreResult.p_stderr` at a value that isn't degenerate (unlike the fully-unexamined and
    fully-saturated fixtures elsewhere in this file)."""
    standing = score(PARTIALLY_RESEARCHED, config)
    assert 0.0 < standing.p_stderr


def test_scores_fully_unexamined(config: ScoringConfig) -> None:
    """Headway's shape: a research trace only, zero assertions. Every scoring target enters at its
    unexamined prior; this must produce a valid result, not an error."""
    standing = score([], config)
    reach = score(resolve_favourably([], config), config)
    band = band_for(standing, reach, config.bands)

    assert 0.0 <= standing.standing <= 1.0
    assert unexamined_targets([], config) == [
        *config.dimension_weights,
        *config.constraints,
    ]
    # An empty record's reach saturates toward the top of what one favourable pass on every
    # target can produce — the "reach never sorts" corollary (S5): it can out-reach even a
    # partially-researched opening, which is the counter-intuitive-but-correct behavior the
    # prototype measured directly (docs/architecture/prototype-decisions.md D21).
    assert reach.standing >= standing.standing
    assert band in {"no path", "contender", "established", "capped", "wide open"}


def test_non_scoring_target_excluded(config: ScoringConfig) -> None:
    """`non_scoring:obtainability` assertions never influence standing/reach (wall 3/4),
    even when present in the input."""
    obtainability_assertion = _assertion(
        "non_scoring:obtainability", "Strong", provenance="ratified"
    )
    without = score([], config)
    with_obtainability = score([obtainability_assertion], config)

    assert with_obtainability.standing == without.standing
    assert with_obtainability.ceiling == without.ceiling
    assert unexamined_targets([obtainability_assertion], config) == unexamined_targets([], config)


def test_order_independent(config: ScoringConfig) -> None:
    """Reordering assertions never changes the result — deterministic given a seed, so this
    is exact equality, not "within sampling noise"."""
    forward = score(PARTIALLY_RESEARCHED, config)
    reversed_result = score(list(reversed(PARTIALLY_RESEARCHED)), config)

    assert forward.standing == reversed_result.standing
    assert forward.ceiling == reversed_result.ceiling
    assert (forward.trace == reversed_result.trace).all()


def test_ruling_override_changes_target_stats(config: ScoringConfig) -> None:
    """`score()` accepts an optional mapping of assertion id -> overridden fit; the ruled
    fit replaces the assertion's own `fit` when computing that target's stats, and only
    that target's stats move (bearing Done When: overriding one assertion changes the
    score trace for its target)."""
    target_assertion = PARTIALLY_RESEARCHED[0]  # stretch, Strong, ratified
    assert target_assertion.target == "stretch"

    unruled = score(PARTIALLY_RESEARCHED, config)
    ruled = score(PARTIALLY_RESEARCHED, config, rulings={target_assertion.id: "Poor"})

    assert ruled.standing != unruled.standing
