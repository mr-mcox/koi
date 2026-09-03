"""Unit tests for the `bump-research-turns-budget` CLI command — the manual
override the operator uses to raise one opening's cap above the flat
scoring.yaml default (F23: "a way for me to bump it up per opening")."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from screen.intake import cli as cli_module
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


def test_bump_sets_new_budget(tmp_path: Path) -> None:
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme", budget=5)

    result = CliRunner().invoke(
        cli_module.bump_research_turns_budget,
        ["acme--eng", "12"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    assert get_opening(conn, "acme--eng").research_turns_budget == 12  # type: ignore[union-attr]


def test_bump_leaves_other_openings_untouched(tmp_path: Path) -> None:
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme", budget=5)
    _seed_opening(tmp_path / "screen.db", "widgets--eng", "widgets", budget=5)

    CliRunner().invoke(
        cli_module.bump_research_turns_budget,
        ["acme--eng", "12"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    conn = connect(tmp_path / "screen.db")
    assert get_opening(conn, "widgets--eng").research_turns_budget == 5  # type: ignore[union-attr]


def test_bump_unknown_opening_raises_click_exception(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_module.bump_research_turns_budget,
        ["no-such-opening", "12"],
        env=env_for(tmp_path),
    )
    assert result.exit_code != 0
    assert "no-such-opening" in result.output
