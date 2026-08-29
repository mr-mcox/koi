"""Tests for the digest generation service: cache-aware, invalidated by
assertion count (append-only assertions make count comparison exact)."""

from datetime import UTC, datetime
from pathlib import Path

from screen.digest.fakes import FakeDigester
from screen.digest.service import digest_for_target
from screen.store.db import connect
from screen.store.repo import append_assertions, upsert_company, upsert_opening
from screen.types import Assertion, Citation, Company, Opening

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
_OPENING_ID = "acme--eng-abc123"


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


def _seeded_conn(tmp_path: Path):
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id=_OPENING_ID,
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/jobs/1",
            research_trace_id="tx0123456789abcdef",
            created_at=_NOW,
        ),
    )
    return conn


def test_generates_a_digest_from_current_assertions(tmp_path: Path) -> None:
    conn = _seeded_conn(tmp_path)
    append_assertions(conn, [_assertion("stretch")], opening_id=_OPENING_ID)
    digester = FakeDigester(["High-bar engineering culture."])

    result = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="stretch",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )

    assert result == "High-bar engineering culture."


def test_second_call_with_unchanged_assertions_returns_cached_value(tmp_path: Path) -> None:
    conn = _seeded_conn(tmp_path)
    append_assertions(conn, [_assertion("stretch")], opening_id=_OPENING_ID)
    digester = FakeDigester(["first", "second"])

    first = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="stretch",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )
    second = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="stretch",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )

    assert first == "first"
    assert second == "first"
    assert digester.calls == 1


def test_new_assertion_invalidates_the_cache(tmp_path: Path) -> None:
    conn = _seeded_conn(tmp_path)
    append_assertions(conn, [_assertion("stretch")], opening_id=_OPENING_ID)
    digester = FakeDigester(["first", "second"])

    first = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="stretch",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )
    append_assertions(conn, [_assertion("stretch")], opening_id=_OPENING_ID)
    second = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="stretch",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )

    assert first == "first"
    assert second == "second"
    assert digester.calls == 2
