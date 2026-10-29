"""Tests for `screen.store.repo` — the layer intake/pipeline.py calls."""

from datetime import UTC, datetime
from pathlib import Path

from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertion_rulings_for_opening,
    assertions_for_opening,
    get_company,
    get_opening,
    list_openings,
    set_opening_stage,
    upsert_assertion_ruling,
    upsert_company,
    upsert_opening,
)
from screen.types import AssertionRuling, Company, Opening
from tests.helpers import canned_assertion, seed_opening

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_upsert_company_then_select(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    row = conn.execute("SELECT * FROM companies WHERE id = 'acme'").fetchone()
    assert row["name"] == "Acme Corp"


def test_upsert_company_is_idempotent_on_repeated_intake(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    upsert_company(conn, Company(id="acme", name="Acme Corp (renamed)", created_at=_NOW))
    rows = conn.execute("SELECT * FROM companies WHERE id = 'acme'").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Acme Corp (renamed)"


def test_upsert_opening_then_select(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    opening = Opening(
        id="acme--eng-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=_NOW,
    )
    upsert_opening(conn, opening)
    row = conn.execute("SELECT * FROM openings WHERE id = 'acme--eng-abc123'").fetchone()
    assert row["title"] == "Staff Engineer"


def test_append_assertions_then_read_back_in_created_at_order(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
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
    first = canned_assertion("craft_direction")
    second = canned_assertion("trajectory")
    append_assertions(conn, [first], opening_id="acme--eng-abc123")
    append_assertions(conn, [second], opening_id="acme--eng-abc123")

    result = assertions_for_opening(conn, "acme--eng-abc123")
    assert [a.target for a in result] == ["craft_direction", "trajectory"]


def test_assertions_for_opening_returns_empty_list_when_none_exist(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
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
    assert assertions_for_opening(conn, "acme--eng-abc123") == []


def test_get_company_returns_none_when_absent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    assert get_company(conn, "no-such-company") is None


def test_get_company_returns_the_row(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    company = get_company(conn, "acme")
    assert company == Company(id="acme", name="Acme Corp", created_at=_NOW)


def test_get_opening_returns_none_when_absent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    assert get_opening(conn, "no-such-opening") is None


def test_get_opening_returns_the_row(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    opening = Opening(
        id="acme--eng-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=_NOW,
    )
    upsert_opening(conn, opening)
    assert get_opening(conn, "acme--eng-abc123") == opening


def test_list_openings_returns_all_in_created_at_order(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    first = Opening(
        id="acme--eng-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=_NOW,
    )
    second = Opening(
        id="acme--pm-def456",
        company_id="acme",
        title="Product Manager",
        url="https://example.com/jobs/2",
        research_trace_id="tx9876543210fedcba",
        created_at=_NOW.replace(hour=13),
    )
    upsert_opening(conn, second)
    upsert_opening(conn, first)
    assert list_openings(conn) == [first, second]


def test_list_openings_returns_empty_list_when_none_exist(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    assert list_openings(conn) == []


def test_list_openings_filters_by_stage(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    screening = Opening(
        id="acme--eng-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=_NOW,
    )
    applied = Opening(
        id="acme--pm-def456",
        company_id="acme",
        title="Product Manager",
        url="https://example.com/jobs/2",
        research_trace_id="tx9876543210fedcba",
        created_at=_NOW.replace(hour=13),
        stage="applied",
    )
    upsert_opening(conn, screening)
    upsert_opening(conn, applied)

    assert list_openings(conn, stage="screening") == [screening]
    assert list_openings(conn, stage="applied") == [applied]
    assert list_openings(conn) == [screening, applied]


def test_upsert_opening_persists_stage_change(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme Corp", created_at=_NOW))
    opening = Opening(
        id="acme--eng-abc123",
        company_id="acme",
        title="Staff Engineer",
        url="https://example.com/jobs/1",
        research_trace_id="tx0123456789abcdef",
        created_at=_NOW,
    )
    upsert_opening(conn, opening)

    moved = opening.model_copy(update={"stage": "pursuing"})
    upsert_opening(conn, moved)

    assert get_opening(conn, "acme--eng-abc123") == moved


def test_assertion_rulings_for_opening_returns_empty_list_when_none_exist(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn, assertions=[canned_assertion()])
    assert assertion_rulings_for_opening(conn, "acme--eng-abc123") == []


def test_assertion_rulings_for_opening_returns_rulings_for_its_assertions(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "screen.db")
    assertion = canned_assertion()
    seed_opening(conn, assertions=[assertion])
    ruling = AssertionRuling(assertion_id=assertion.id, fit="Mixed", created_at=_NOW)
    conn.execute(
        """INSERT INTO assertion_rulings (id, assertion_id, fit, created_at)
           VALUES (:id, :assertion_id, :fit, :created_at)""",
        {
            "id": ruling.id,
            "assertion_id": ruling.assertion_id,
            "fit": ruling.fit,
            "created_at": ruling.created_at.isoformat(),
        },
    )
    conn.commit()

    result = assertion_rulings_for_opening(conn, "acme--eng-abc123")

    assert result == [ruling]


def test_assertion_rulings_for_opening_excludes_other_openings(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    assertion = canned_assertion()
    seed_opening(conn, assertions=[assertion])
    upsert_opening(
        conn,
        Opening(
            id="acme--pm-def456",
            company_id="acme",
            title="Product Manager",
            url="https://example.com/jobs/2",
            research_trace_id="tx9876543210fedcba",
            created_at=_NOW,
        ),
    )
    other_assertion = canned_assertion("trajectory")
    append_assertions(conn, [other_assertion], opening_id="acme--pm-def456")
    conn.execute(
        """INSERT INTO assertion_rulings (id, assertion_id, fit, created_at)
           VALUES (:id, :assertion_id, :fit, :created_at)""",
        {
            "id": "ruling-other",
            "assertion_id": other_assertion.id,
            "fit": "Poor",
            "created_at": _NOW.isoformat(),
        },
    )
    conn.commit()

    assert assertion_rulings_for_opening(conn, "acme--eng-abc123") == []
    assert assertion.id != other_assertion.id


def test_upsert_assertion_ruling_then_read_back(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    assertion = canned_assertion()
    seed_opening(conn, assertions=[assertion])
    ruling = AssertionRuling(assertion_id=assertion.id, fit="Mixed", created_at=_NOW)

    upsert_assertion_ruling(conn, ruling)

    assert assertion_rulings_for_opening(conn, "acme--eng-abc123") == [ruling]


def test_upsert_assertion_ruling_replaces_prior_ruling_for_same_assertion(
    tmp_path: Path,
) -> None:
    """Re-rating the same assertion replaces the stored ruling, not appends
    (Approach: "repeated ratings replace the previous one, not append")."""
    conn = connect(tmp_path / "screen.db")
    assertion = canned_assertion()
    seed_opening(conn, assertions=[assertion])
    upsert_assertion_ruling(
        conn, AssertionRuling(assertion_id=assertion.id, fit="Poor", created_at=_NOW)
    )
    second = AssertionRuling(
        assertion_id=assertion.id, fit="Strong", created_at=_NOW.replace(hour=13)
    )

    upsert_assertion_ruling(conn, second)

    result = assertion_rulings_for_opening(conn, "acme--eng-abc123")
    assert result == [second]


def test_set_opening_stage_moves_only_the_named_openings(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn, "acme--a")
    seed_opening(conn, "acme--b")
    seed_opening(conn, "acme--c")

    set_opening_stage(conn, ["acme--a", "acme--c"], "closed")

    assert sorted(o.id for o in list_openings(conn, stage="closed")) == ["acme--a", "acme--c"]
    assert [o.id for o in list_openings(conn, stage="screening")] == ["acme--b"]
