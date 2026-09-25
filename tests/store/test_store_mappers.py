"""Round-trip tests for hand-written row <-> domain-model mappers.

No ORM: `screen.types` stays the one domain
model; these functions are the entire seam between it and SQLite rows.
"""

from datetime import UTC, datetime

import pytest

from screen.store.mappers import (
    assertion_from_row,
    assertion_ruling_from_row,
    assertion_ruling_to_row,
    assertion_to_row,
    company_from_row,
    company_to_row,
    comparison_from_row,
    comparison_to_row,
    dimension_digest_from_row,
    dimension_digest_to_row,
    opening_from_row,
    opening_to_row,
)
from screen.types import (
    Assertion,
    AssertionRuling,
    Citation,
    Company,
    Comparison,
    DimensionDigest,
    Opening,
)

_CREATED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _citation() -> Citation:
    return Citation(
        url="https://example.com/jobs/1",
        quote="Build and own the platform.",
        host="example.com",
        source_provenance="official",
        independent=True,
        source_date=None,
    )


def test_company_round_trips_through_row() -> None:
    company = Company(id="acme", name="Acme Corp", created_at=_CREATED_AT)
    row = company_to_row(company)
    assert company_from_row(row) == company


def test_opening_round_trips_through_row() -> None:
    opening = Opening(
        id="acme--staff-engineer-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=_CREATED_AT,
    )
    row = opening_to_row(opening)
    assert opening_from_row(row) == opening


def test_opening_round_trips_non_default_stage_through_row() -> None:
    opening = Opening(
        id="acme--staff-engineer-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=_CREATED_AT,
        stage="applied",
    )
    row = opening_to_row(opening)
    assert row["stage"] == "applied"
    assert opening_from_row(row) == opening


def test_assertion_round_trips_through_row() -> None:
    assertion = Assertion(
        target="craft_direction",
        fit="Strong",
        provenance="model_proposed",
        chunk="10+ years in platform engineering.",
        citations=[_citation()],
        created_at=_CREATED_AT,
    )
    row = assertion_to_row(assertion, opening_id="acme--staff-engineer-abc123")
    fetched = assertion_from_row(row)
    assert fetched is not None
    assert fetched == assertion


def test_assertion_row_carries_opening_id_for_the_foreign_key() -> None:
    assertion = Assertion(
        target="domain",
        fit="Mixed",
        provenance="model_proposed",
        chunk="Some domain claim.",
        citations=[_citation()],
        created_at=_CREATED_AT,
    )
    row = assertion_to_row(assertion, opening_id="acme--staff-engineer-abc123")
    assert row["opening_id"] == "acme--staff-engineer-abc123"


def test_assertion_ruling_round_trips_through_row() -> None:
    ruling = AssertionRuling(
        assertion_id="00000000-0000-0000-0000-000000000001",
        fit="Strong",
        created_at=_CREATED_AT,
    )
    row = assertion_ruling_to_row(ruling)
    assert assertion_ruling_from_row(row) == ruling


def test_assertion_from_row_warns_and_returns_none_for_retired_target() -> None:
    """Read-path tolerance: retired rubric targets don't crash the mapper."""
    assertion = Assertion(
        target="craft_direction",
        fit="Strong",
        provenance="model_proposed",
        chunk="10+ years in platform engineering.",
        citations=[_citation()],
        created_at=_CREATED_AT,
    )
    row = assertion_to_row(assertion, opening_id="acme--staff-engineer-abc123")
    row["target"] = "peer"
    with pytest.warns(UserWarning, match="retired/unknown target 'peer'"):
        assert assertion_from_row(row) is None


def test_assertion_from_row_warns_and_returns_none_for_renamed_target() -> None:
    """A renamed dimension is treated as retired at the read boundary so stale
    assertions don't silently adopt the new semantics."""
    assertion = Assertion(
        target="craft_direction",
        fit="Strong",
        provenance="model_proposed",
        chunk="AI/ML work.",
        citations=[_citation()],
        created_at=_CREATED_AT,
    )
    row = assertion_to_row(assertion, opening_id="acme--staff-engineer-abc123")
    row["target"] = "stretch"
    with pytest.warns(UserWarning, match="retired/unknown target 'stretch'"):
        assert assertion_from_row(row) is None


def test_dimension_digest_round_trips_through_row() -> None:
    digest = DimensionDigest(
        opening_id="acme--staff-engineer-abc123",
        target="craft_direction",
        digest="Summary text.",
        assertion_count=3,
        computed_at=_CREATED_AT,
    )
    row = dimension_digest_to_row(digest)
    fetched = dimension_digest_from_row(row)
    assert fetched is not None
    assert fetched == digest


def test_dimension_digest_from_row_warns_and_returns_none_for_retired_target() -> None:
    digest = DimensionDigest(
        opening_id="acme--staff-engineer-abc123",
        target="craft_direction",
        digest="Summary text.",
        assertion_count=3,
        computed_at=_CREATED_AT,
    )
    row = dimension_digest_to_row(digest)
    row["target"] = "peer"
    with pytest.warns(UserWarning, match="retired/unknown target 'peer'"):
        assert dimension_digest_from_row(row) is None


def test_comparison_round_trips_through_row() -> None:
    comparison = Comparison(
        opening_a_id="a",
        opening_b_id="b",
        target="craft_direction",
        outcome="a",
        predicted_a_beats_b=0.75,
        created_at=_CREATED_AT,
    )
    row = comparison_to_row(comparison)
    fetched = comparison_from_row(row)
    assert fetched is not None
    assert fetched == comparison


def test_comparison_from_row_warns_and_returns_none_for_retired_target() -> None:
    comparison = Comparison(
        opening_a_id="a",
        opening_b_id="b",
        target="craft_direction",
        outcome="a",
        predicted_a_beats_b=0.75,
        created_at=_CREATED_AT,
    )
    row = comparison_to_row(comparison)
    row["target"] = "peer"
    with pytest.warns(UserWarning, match="retired/unknown target 'peer'"):
        assert comparison_from_row(row) is None
