"""Tests for the digest generation service: cache-aware, invalidated by
assertion count (append-only assertions make count comparison exact)."""

from datetime import UTC, datetime
from pathlib import Path

from screen.digest.fakes import FakeDigester
from screen.digest.service import digest_for_target, update_digests_for_opening
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    get_dimension_digest,
    upsert_company,
    upsert_opening,
)
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


def _assertion(target: str = "craft_direction") -> Assertion:
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
    append_assertions(conn, [_assertion("craft_direction")], opening_id=_OPENING_ID)
    digester = FakeDigester(["High-bar engineering culture."])

    result = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="craft_direction",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )

    assert result == "High-bar engineering culture."


def test_second_call_with_unchanged_assertions_returns_cached_value(tmp_path: Path) -> None:
    conn = _seeded_conn(tmp_path)
    append_assertions(conn, [_assertion("craft_direction")], opening_id=_OPENING_ID)
    digester = FakeDigester(["first", "second"])

    first = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="craft_direction",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )
    second = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="craft_direction",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )

    assert first == "first"
    assert second == "first"
    assert digester.calls == 1


def test_new_assertion_invalidates_the_cache(tmp_path: Path) -> None:
    conn = _seeded_conn(tmp_path)
    append_assertions(conn, [_assertion("craft_direction")], opening_id=_OPENING_ID)
    digester = FakeDigester(["first", "second"])

    first = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="craft_direction",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )
    append_assertions(conn, [_assertion("craft_direction")], opening_id=_OPENING_ID)
    second = digest_for_target(
        conn,
        opening_id=_OPENING_ID,
        target="craft_direction",
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )

    assert first == "first"
    assert second == "second"
    assert digester.calls == 2


def test_update_digests_for_opening_warms_every_target_with_assertions(tmp_path: Path) -> None:
    """`update_digests_for_opening` walks every target that has assertions and
    caches a digest for each, so the rating view never hits a cold cache."""
    conn = _seeded_conn(tmp_path)
    append_assertions(
        conn,
        [_assertion("craft_direction"), _assertion("mission")],
        opening_id=_OPENING_ID,
    )
    digester = FakeDigester(["stretch digest", "mission digest"])

    update_digests_for_opening(
        conn,
        opening_id=_OPENING_ID,
        digester=digester,
        rubric_text="rubric",
        now=_NOW,
    )

    assert digester.calls == 2
    assert get_dimension_digest(conn, _OPENING_ID, "craft_direction").digest == "stretch digest"
    assert get_dimension_digest(conn, _OPENING_ID, "mission").digest == "mission digest"


def test_update_digests_for_opening_is_idempotent_when_assertions_unchanged(
    tmp_path: Path,
) -> None:
    """A second call with no new assertions must not re-invoke the digester. Staleness is
    keyed on assertion count, and assertions are append-only (Wall 6), so an unchanged
    count is exact evidence that nothing needs recomputing — not a heuristic."""
    conn = _seeded_conn(tmp_path)
    append_assertions(conn, [_assertion("craft_direction")], opening_id=_OPENING_ID)
    digester = FakeDigester(["stretch digest"])

    update_digests_for_opening(
        conn, opening_id=_OPENING_ID, digester=digester, rubric_text="rubric", now=_NOW
    )
    update_digests_for_opening(
        conn, opening_id=_OPENING_ID, digester=digester, rubric_text="rubric", now=_NOW
    )

    assert digester.calls == 1
