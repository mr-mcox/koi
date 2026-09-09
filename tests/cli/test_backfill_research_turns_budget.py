"""Unit tests for the `backfill-research-turns-budget` CLI command — seeds
`Opening.research_turns_budget` for every opening already in the DB, so existing
openings get the same seeded budget as new ones."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from screen.intake import cli as cli_module
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import get_opening, upsert_company, upsert_opening
from screen.types import Company, Opening
from tests.cli.helpers import env_for


def _seed_opening(db_path: Path, opening_id: str, company_id: str, *, budget: int) -> None:
    conn = connect(db_path)
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title="Eng",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            research_turns_budget=budget,
            created_at=datetime.now(UTC),
        ),
    )
    conn.close()


def test_backfill_sets_scoring_yaml_budget_on_every_opening(tmp_path: Path) -> None:
    """Every existing opening — regardless of its current budget — is set to the
    scoring.yaml value, not just openings still at the pre-migration default of 0."""
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme", budget=0)
    _seed_opening(tmp_path / "screen.db", "widgets--eng", "widgets", budget=0)

    result = CliRunner().invoke(
        cli_module.backfill_research_turns_budget, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    expected = load_scoring_config().research_turns_budget
    assert get_opening(conn, "acme--eng").research_turns_budget == expected  # type: ignore[union-attr]
    assert get_opening(conn, "widgets--eng").research_turns_budget == expected  # type: ignore[union-attr]


def test_backfill_reports_opening_count(tmp_path: Path) -> None:
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme", budget=0)

    result = CliRunner().invoke(
        cli_module.backfill_research_turns_budget, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert "1 opening" in result.output


def test_backfill_does_not_touch_manually_bumped_openings_differently(tmp_path: Path) -> None:
    """Backfill is a blanket reset to the scoring.yaml value — not a "fill only if
    zero" operation. A prior manual bump is overwritten, same as a fresh 0 row."""
    expected = load_scoring_config().research_turns_budget
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme", budget=999)

    CliRunner().invoke(
        cli_module.backfill_research_turns_budget, [], env=env_for(tmp_path), catch_exceptions=False
    )

    conn = connect(tmp_path / "screen.db")
    assert get_opening(conn, "acme--eng").research_turns_budget == expected  # type: ignore[union-attr]
