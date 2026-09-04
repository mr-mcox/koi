"""Unit tests for `research --batch N` — round-robin turns across openings
with remaining research_turns_budget headroom, before the algorithmic
research-pass bandit exists (bearing: simple deterministic fill)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from screen.intake import cli as cli_module
from screen.research.actions import SearchAction, StopAction
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import append_assertions, upsert_company, upsert_opening
from screen.types import Assertion, Citation, Company, Opening
from tests.cli.helpers import env_for, patch_digester, patch_extractor

_QUERY = "extra search"


def _seed_opening_with_trace(
    tmp_path: Path, opening_id: str, company_id: str, *, budget: int
) -> Path:
    conn = connect(tmp_path / "screen.db")
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    trace_path = tmp_path / "research_traces" / f"{opening_id}-trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://example.com/{opening_id}"
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {
                    "results": [{"url": url, "raw_content": f"Posting for {opening_id}."}]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
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
    return trace_path


def _search_then_stop_planner() -> FakePlanner:
    return FakePlanner(sequence=[[SearchAction(query=_QUERY)], [StopAction(reason="done")]])


def test_batch_runs_across_openings_with_remaining_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=2)
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=2)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["4"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "acme--eng" in result.output
    assert "widgets--eng" in result.output


def test_batch_skips_openings_with_no_remaining_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=1)  # already exhausted
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=2)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["4"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "acme--eng" not in result.output
    assert "widgets--eng" in result.output


def test_batch_stops_when_all_budgets_exhausted_before_batch_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch of 10 against one opening with 1 turn remaining spends only that 1 turn."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=2)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["10"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "spent 1 turn(s) across 1 opening(s)" in result.output


def test_batch_with_no_openings_having_budget_is_a_no_op(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=1)

    result = CliRunner().invoke(
        cli_module.research_batch, ["4"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "spent 0 turn(s) across 0 opening(s)" in result.output


def test_batch_size_zero_is_a_no_op(tmp_path: Path) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)

    result = CliRunner().invoke(
        cli_module.research_batch, ["0"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "spent 0 turn(s) across 0 opening(s)" in result.output


def test_batch_revisits_same_opening_across_rounds_within_one_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One opening with 3 turns of headroom, batch_size=3: the round-robin loop
    revisits the same (only) opening across three rounds, exercising the
    already-touched branch on round 2+."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=4)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["3"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "spent 3 turn(s) across 1 opening(s)" in result.output


def test_batch_stops_a_later_opening_mid_round_when_turns_left_hits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two openings, batch_size=1: the first opening exhausts the entire batch,
    so the round-robin loop's turns_left<=0 guard fires on the second opening."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=5)
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=5)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["1"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "spent 1 turn(s) across 1 opening(s)" in result.output


def _seed_assertions(tmp_path: Path, opening_id: str, targets: list[str], count: int) -> None:
    conn = connect(tmp_path / "screen.db")
    assertions = [
        Assertion(
            target=target,  # type: ignore[arg-type]
            fit="Strong",
            provenance="ratified",
            chunk="chunk",
            citations=[
                Citation(
                    url="https://example.com",
                    quote="q",
                    host="example.com",
                    source_provenance="official",
                    independent=True,
                    source_date=None,
                )
            ],
            created_at=datetime.now(UTC),
        )
        for target in targets
        for _ in range(count)
    ]
    append_assertions(conn, assertions, opening_id=opening_id)
    conn.close()


def test_batch_draws_the_higher_uncertainty_opening_more_often(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wide-half-width (unexamined) opening receives turns more often than one whose
    targets are already heavily, consistently examined, over a batch of many draws
    (research-pass-bandit bearing Done When)."""
    config = load_scoring_config()
    all_targets = list(config.dimension_weights) + list(config.constraints)
    _seed_opening_with_trace(tmp_path, "wide--eng", "wide", budget=50)
    _seed_opening_with_trace(tmp_path, "narrow--eng", "narrow", budget=50)
    _seed_assertions(
        tmp_path, "narrow--eng", all_targets, 10
    )  # heavily examined -> low uncertainty
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["30"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert result.output.count("drew wide--eng") > result.output.count("drew narrow--eng")


def test_batch_never_draws_a_budget_exhausted_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=1)  # already exhausted
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=5)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["5"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    assert "drew acme--eng" not in result.output


def test_batch_prints_one_draw_line_per_turn_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=4)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research_batch, ["3"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"batch failed: {result.output}"
    draw_lines = [line for line in result.output.splitlines() if line.startswith("drew ")]
    assert len(draw_lines) == 3
    assert all("rank" in line and "p=" in line for line in draw_lines)


def test_batch_draw_sequence_is_reproducible_for_an_unchanged_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two invocations against identical seed data produce identical draw sequences
    (config.seed determinism, research-pass-bandit bearing Done When)."""
    _seed_opening_with_trace(tmp_path, "acme--eng", "acme", budget=50)
    _seed_opening_with_trace(tmp_path, "widgets--eng", "widgets", budget=50)
    monkeypatch.setattr(
        cli_module, "_build_client", lambda: FakeBrowser(search_fixtures={_QUERY: []})
    )
    monkeypatch.setattr(cli_module, "_build_planner", _search_then_stop_planner)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    def _draws(output: str) -> list[str]:
        return [line for line in output.splitlines() if line.startswith("drew ")]

    first = CliRunner().invoke(
        cli_module.research_batch, ["10"], env=env_for(tmp_path), catch_exceptions=False
    )
    assert first.exit_code == 0, f"batch failed: {first.output}"

    tmp_path_2 = tmp_path.parent / f"{tmp_path.name}-replay"
    _seed_opening_with_trace(tmp_path_2, "acme--eng", "acme", budget=50)
    _seed_opening_with_trace(tmp_path_2, "widgets--eng", "widgets", budget=50)
    second = CliRunner().invoke(
        cli_module.research_batch, ["10"], env=env_for(tmp_path_2), catch_exceptions=False
    )
    assert second.exit_code == 0, f"batch failed: {second.output}"
    assert _draws(first.output) == _draws(second.output)
