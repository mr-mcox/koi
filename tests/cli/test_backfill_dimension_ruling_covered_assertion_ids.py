"""Unit tests for the `backfill-dimension-ruling-covered-assertion-ids` CLI command —
populates `covered_assertion_ids` for existing `DimensionRuling` rows predating that field
(dimension-ruling-drift bearing Done When)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from screen.extract.extract import Assertion
from screen.intake import cli as cli_module
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    dimension_rulings_for_opening,
    upsert_company,
    upsert_dimension_ruling,
    upsert_opening,
)
from screen.types import Citation, Company, DimensionRuling, Opening
from tests.cli.helpers import env_for

_NOW = datetime(2026, 8, 31, tzinfo=UTC)

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)


def _seed(db_path: Path) -> tuple[str, str]:
    conn = connect(db_path)
    upsert_company(conn, Company(id="acme", name="Acme Inc", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--eng",
            company_id="acme",
            title="Eng",
            url="https://example.com/acme--eng",
            research_trace_id="tx-acme--eng",
            research_turns_budget=5,
            created_at=_NOW,
        ),
    )
    stretch = Assertion(
        target="stretch",
        fit="Strong",
        provenance="ratified",
        chunk="chunk",
        citations=[_CITATION],
        created_at=_NOW,
    )
    other_target = Assertion(
        target="schematic",
        fit="Strong",
        provenance="ratified",
        chunk="chunk",
        citations=[_CITATION],
        created_at=_NOW,
    )
    append_assertions(conn, [stretch, other_target], opening_id="acme--eng")
    upsert_dimension_ruling(
        conn,
        DimensionRuling(
            opening_id="acme--eng",
            target="stretch",
            mean=0.5,
            settledness=0.8,
            created_at=_NOW,
        ),
    )
    conn.close()
    return "acme--eng", stretch.id


def test_backfill_populates_covered_assertion_ids_from_existing_assertions(
    tmp_path: Path,
) -> None:
    opening_id, stretch_id = _seed(tmp_path / "screen.db")

    result = CliRunner().invoke(
        cli_module.backfill_dimension_ruling_covered_assertion_ids,
        [],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    (ruling,) = dimension_rulings_for_opening(conn, opening_id)
    assert ruling.covered_assertion_ids == [stretch_id]


def test_backfill_does_not_touch_assertions_from_other_targets(tmp_path: Path) -> None:
    opening_id, stretch_id = _seed(tmp_path / "screen.db")

    CliRunner().invoke(
        cli_module.backfill_dimension_ruling_covered_assertion_ids,
        [],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    conn = connect(tmp_path / "screen.db")
    (ruling,) = dimension_rulings_for_opening(conn, opening_id)
    assert stretch_id in ruling.covered_assertion_ids
    assert len(ruling.covered_assertion_ids) == 1


def test_backfill_reports_ruling_count(tmp_path: Path) -> None:
    _seed(tmp_path / "screen.db")

    result = CliRunner().invoke(
        cli_module.backfill_dimension_ruling_covered_assertion_ids,
        [],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    assert "1 dimension ruling" in result.output


def test_backfill_is_a_blanket_reset_not_fill_if_empty(tmp_path: Path) -> None:
    """Re-running backfill overwrites `covered_assertion_ids` from current assertions
    again, same blanket-reset pattern as `backfill-research-turns-budget` — not a
    fill-only-if-empty operation."""
    opening_id, stretch_id = _seed(tmp_path / "screen.db")
    conn = connect(tmp_path / "screen.db")
    upsert_dimension_ruling(
        conn,
        DimensionRuling(
            opening_id=opening_id,
            target="stretch",
            mean=0.5,
            settledness=0.8,
            created_at=_NOW,
            covered_assertion_ids=["stale-id"],
        ),
    )
    conn.close()

    CliRunner().invoke(
        cli_module.backfill_dimension_ruling_covered_assertion_ids,
        [],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    conn = connect(tmp_path / "screen.db")
    (ruling,) = dimension_rulings_for_opening(conn, opening_id)
    assert ruling.covered_assertion_ids == [stretch_id]
