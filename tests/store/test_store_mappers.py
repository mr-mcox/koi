"""Round-trip tests for hand-written row <-> domain-model mappers.

No ORM (score-persistence bearing): `screen.types` stays the one domain
model; these functions are the entire seam between it and SQLite rows.
"""

from datetime import UTC, datetime

from screen.store.mappers import (
    assertion_from_row,
    assertion_ruling_from_row,
    assertion_ruling_to_row,
    assertion_to_row,
    company_from_row,
    company_to_row,
    opening_from_row,
    opening_to_row,
)
from screen.types import Assertion, AssertionRuling, Citation, Company, Opening

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


def test_assertion_round_trips_through_row() -> None:
    assertion = Assertion(
        target="stretch",
        fit="Strong",
        provenance="model_proposed",
        chunk="10+ years in platform engineering.",
        citations=[_citation()],
        created_at=_CREATED_AT,
    )
    row = assertion_to_row(assertion, opening_id="acme--staff-engineer-abc123")
    assert assertion_from_row(row) == assertion


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
