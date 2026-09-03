"""Tests for screen.score.triage: selecting the highest-leverage rating tasks per opening."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from screen.score.loader import load_scoring_config
from screen.score.triage import rating_task_candidates
from screen.score.types import ScoringConfig
from screen.types import (
    Assertion,
    Citation,
    DimensionRuling,
    Fit,
    Provenance,
    Target,
)

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


def test_budget_is_respected(config: ScoringConfig) -> None:
    """The configured rating_task_budget caps the number of returned tasks."""
    assertions = [
        _assertion("stretch", "Strong"),
        _assertion("schematic", "Strong"),
        _assertion("peer", "Strong"),
        _assertion("trajectory", "Strong"),
        _assertion("mission", "Strong"),
        _assertion("agentic", "Strong"),
    ]
    candidates = rating_task_candidates(assertions, config)
    assert len(candidates) <= config.rating_task_budget


def test_unrated_targets_outrank_already_ruled_assertions(config: ScoringConfig) -> None:
    """A dimension with no rulings at all is unexamined and has far larger swing potential
    than an assertion whose target already has a dimension-level pin covering it."""
    stretch_assertion = _assertion("stretch", "Strong")
    assertions = [
        stretch_assertion,
        _assertion("schematic", "Strong"),
    ]
    dimension_rulings = {
        "stretch": DimensionRuling(
            opening_id="o1",
            target="stretch",
            mean=0.9,
            settledness=1.0,
            created_at=_NOW,
            covered_assertion_ids=[stretch_assertion.id],
        ),
    }
    candidates = rating_task_candidates(assertions, config, dimension_rulings=dimension_rulings)
    assert any(c.target == "schematic" for c in candidates)
    assert not any(c.target == "stretch" for c in candidates)


def test_high_weight_wide_target_outranks_low_weight_narrow_target(config: ScoringConfig) -> None:
    """A high-weight, unexamined dimension should rank above a low-weight, already-ratified
    dimension (wide half-width + heavy weight = larger potential swing)."""
    assertions = [
        # weight 3, unexamined -> wide Uniform(-1, 1), potential swing across the whole scale
        _assertion("stretch", "Strong"),
        # weight 1, ratified -> very narrow, barely moves
        _assertion("domain", "Strong", "ratified"),
    ]
    candidates = rating_task_candidates(assertions, config)
    assert candidates[0].target == "stretch"


def test_assertion_ruling_reduces_its_task_swing(config: ScoringConfig) -> None:
    """An assertion that has already been ruled should not appear as a candidate; the same
    assertion unrated should appear."""
    a = _assertion("stretch", "Poor")
    candidates = rating_task_candidates([a], config)
    assert any(c.assertion_id == a.id and c.target == "stretch" for c in candidates)

    candidates = rating_task_candidates([a], config, rulings={a.id: "Poor"})
    assert not any(c.assertion_id == a.id for c in candidates)


def test_symmetric_swing_nonnegative(config: ScoringConfig) -> None:
    """Swing is the magnitude of standing movement between best- and worst-case override,
    so it is always >= 0 for every candidate task."""
    assertions = [_assertion("stretch", "Strong")]
    candidates = rating_task_candidates(assertions, config)
    assert len(candidates) == 2  # the assertion itself, and the whole-dimension pin
    assert all(c.swing >= 0.0 for c in candidates)


def test_full_dimension_pin_excludes_covered_assertions_underneath(
    config: ScoringConfig,
) -> None:
    """If a dimension is pinned and its snapshot covers an assertion, that assertion is
    not worth rating on its own — the pin supersedes it."""
    a = _assertion("stretch", "Strong")
    pin = DimensionRuling(
        opening_id="o1",
        target="stretch",
        mean=0.0,
        settledness=0.5,
        created_at=_NOW,
        covered_assertion_ids=[a.id],
    )
    candidates = rating_task_candidates([a], config, dimension_rulings={"stretch": pin})
    assert not any(c.assertion_id == a.id for c in candidates)


def test_uncovered_assertion_under_a_pin_still_appears_as_a_candidate(
    config: ScoringConfig,
) -> None:
    """An assertion filed after a pin's snapshot is new evidence the pin hasn't accounted
    for — rating it can still move the blended standing, so it stays a candidate
    (dimension-ruling-drift bearing Done When)."""
    covered = _assertion("stretch", "Strong")
    new = _assertion("stretch", "Poor", "ratified")
    pin = DimensionRuling(
        opening_id="o1",
        target="stretch",
        mean=0.0,
        settledness=0.5,
        created_at=_NOW,
        covered_assertion_ids=[covered.id],
    )
    candidates = rating_task_candidates([covered, new], config, dimension_rulings={"stretch": pin})
    assert any(c.assertion_id == new.id for c in candidates)


def test_stale_pinned_target_reappears_as_a_whole_dimension_candidate(
    config: ScoringConfig,
) -> None:
    """A pinned target with an uncovered assertion is reopened for rating at the whole-
    dimension level too, not just at the assertion level — the pin itself is stale
    (dimension-ruling-drift bearing Done When: reopening is binary on any uncovered
    assertion)."""
    covered = _assertion("stretch", "Strong")
    new = _assertion("stretch", "Poor", "ratified")
    pin = DimensionRuling(
        opening_id="o1",
        target="stretch",
        mean=0.0,
        settledness=0.5,
        created_at=_NOW,
        covered_assertion_ids=[covered.id],
    )
    candidates = rating_task_candidates([covered, new], config, dimension_rulings={"stretch": pin})
    assert any(c.target == "stretch" and c.assertion_id is None for c in candidates)


def test_fully_current_pinned_target_does_not_reappear_as_whole_dimension_candidate(
    config: ScoringConfig,
) -> None:
    """A pin whose snapshot covers every assertion under its target is not stale and does
    not reopen at the whole-dimension level (no regression on the shipped
    exclude-pinned-targets contract)."""
    a = _assertion("stretch", "Strong")
    pin = DimensionRuling(
        opening_id="o1",
        target="stretch",
        mean=0.0,
        settledness=0.5,
        created_at=_NOW,
        covered_assertion_ids=[a.id],
    )
    candidates = rating_task_candidates([a], config, dimension_rulings={"stretch": pin})
    assert not any(c.target == "stretch" and c.assertion_id is None for c in candidates)
