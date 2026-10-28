"""Tests for dimension-digest cache repo functions."""

from datetime import UTC, datetime
from pathlib import Path

from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    get_dimension_digest,
    get_dimension_digest_by_id,
    insert_dimension_digest,
)
from tests.helpers import canned_assertion, seed_opening

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_get_dimension_digest_returns_none_when_absent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn)
    assert get_dimension_digest(conn, "acme--eng-abc123", "craft_direction") is None


def test_insert_then_get_dimension_digest_round_trips(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn)
    append_assertions(conn, [canned_assertion("craft_direction")], opening_id="acme--eng-abc123")

    insert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="craft_direction",
        digest="High-bar engineering culture.",
        assertion_count=1,
        computed_at=datetime(2026, 8, 28, 12, 1, tzinfo=UTC),
    )

    record = get_dimension_digest(conn, "acme--eng-abc123", "craft_direction")
    assert record is not None
    assert record.digest == "High-bar engineering culture."
    assert record.assertion_count == 1


def test_insert_dimension_digest_preserves_history_but_get_returns_latest(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn)
    insert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="craft_direction",
        digest="First draft.",
        assertion_count=1,
        computed_at=_NOW,
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="craft_direction",
        digest="Second draft.",
        assertion_count=2,
        computed_at=datetime(2026, 8, 28, 12, 1, tzinfo=UTC),
    )
    record = get_dimension_digest(conn, "acme--eng-abc123", "craft_direction")
    assert record is not None
    assert record.digest == "Second draft."
    assert record.assertion_count == 2


def test_get_dimension_digest_by_id_recovers_a_superseded_version(tmp_path: Path) -> None:
    """The audit path: a `Comparison` points at a digest version that is no longer the
    latest for `(opening_id, target)`. `get_dimension_digest_by_id` must still recover it
    verbatim, not whatever the current cache row holds."""
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn)
    first = insert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="craft_direction",
        digest="First draft.",
        assertion_count=1,
        computed_at=_NOW,
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng-abc123",
        target="craft_direction",
        digest="Second draft.",
        assertion_count=2,
        computed_at=datetime(2026, 8, 28, 12, 1, tzinfo=UTC),
    )

    recovered = get_dimension_digest_by_id(conn, first.id)
    assert recovered is not None
    assert recovered.digest == "First draft."
    assert recovered.assertion_count == 1


def test_get_dimension_digest_by_id_returns_none_when_absent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn)
    assert get_dimension_digest_by_id(conn, "nonexistent-id") is None
