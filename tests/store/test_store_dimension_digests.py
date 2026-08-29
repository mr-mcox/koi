"""Tests for dimension-digest cache repo functions."""

from datetime import UTC, datetime
from pathlib import Path

from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    get_dimension_digest,
    upsert_company,
    upsert_dimension_digest,
    upsert_opening,
)
from screen.types import Assertion, Citation, Company, Opening

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _citation() -> Citation:
    return Citation(
        url="https://example.com/jobs/1",
        quote="Build and own the platform.",
        host="example.com",
        source_provenance="official",
        independent=True,
        source_date=None,
    )


def _assertion(target: str = "stretch") -> Assertion:
    return Assertion(
        target=target,  # type: ignore[arg-type]
        fit="Strong",
        provenance="model_proposed",
        chunk="Synthetic fixture content.",
        citations=[_citation()],
        created_at=_NOW,
    )


def _seed_opening(conn) -> None:
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--eng-abc123",
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/jobs/1",
            research_trace_id="tx0123456789abcdef",
            created_at=_NOW,
        ),
    )


def test_get_dimension_digest_returns_none_when_absent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    _seed_opening(conn)
    assert get_dimension_digest(conn, "acme--eng-abc123", "stretch") is None


def test_upsert_then_get_dimension_digest_round_trips(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    _seed_opening(conn)
    append_assertions(conn, [_assertion("stretch")], opening_id="acme--eng-abc123")

    upsert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="stretch",
        digest="High-bar engineering culture.",
        assertion_count=1,
        computed_at=_NOW,
    )

    record = get_dimension_digest(conn, "acme--eng-abc123", "stretch")
    assert record is not None
    assert record.digest == "High-bar engineering culture."
    assert record.assertion_count == 1


def test_upsert_dimension_digest_overwrites_existing_row(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    _seed_opening(conn)
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="stretch",
        digest="First draft.",
        assertion_count=1,
        computed_at=_NOW,
    )
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="stretch",
        digest="Second draft.",
        assertion_count=2,
        computed_at=_NOW,
    )
    record = get_dimension_digest(conn, "acme--eng-abc123", "stretch")
    assert record is not None
    assert record.digest == "Second draft."
    assert record.assertion_count == 2
