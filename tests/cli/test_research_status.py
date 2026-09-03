"""Unit tests for the `research-status` CLI command — actual vs budgeted
turns per opening, computed from the trace (bearing Done When: report/list
command)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from screen.intake import cli as cli_module
from screen.store.db import connect
from screen.store.repo import upsert_company, upsert_opening
from screen.types import Company, Opening
from tests.cli.helpers import env_for, seed_research_trace


def _seed(tmp_path: Path, opening_id: str, company_id: str, *, budget: int, url: str) -> None:
    conn = connect(tmp_path / "screen.db")
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    trace_path = tmp_path / "research_traces" / f"{opening_id}-trace.jsonl"
    seed_research_trace(trace_path, f"Posting for {opening_id}.", url)
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title="Eng",
            url=url,
            research_trace_id=f"{opening_id}-trace",
            research_turns_budget=budget,
            created_at=datetime.now(UTC),
        ),
    )
    conn.close()


def test_status_lists_actual_and_budgeted_turns_per_opening(tmp_path: Path) -> None:
    _seed(tmp_path, "acme--eng", "acme", budget=5, url="https://example.com/acme")
    _seed(tmp_path, "widgets--eng", "widgets", budget=3, url="https://example.com/widgets")

    result = CliRunner().invoke(
        cli_module.research_status, [], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"status failed: {result.output}"
    assert "acme--eng" in result.output
    assert "1/5" in result.output  # one tavily_extract turn from seed_research_trace
    assert "widgets--eng" in result.output
    assert "1/3" in result.output


def test_status_with_no_openings_reports_none(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_module.research_status, [], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"status failed: {result.output}"
    assert "no openings" in result.output.lower()
