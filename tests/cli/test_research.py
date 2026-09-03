"""Unit tests for the `research` CLI command — resumes an already-identified
opening's research pass from its trace instead of starting over."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from screen.browser import TavilyBrowser
from screen.intake import cli as cli_module
from screen.intake.fakes import FakeTavily
from screen.research.actions import FetchAction, SearchAction, StopAction
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.store.db import connect
from screen.store.repo import get_opening, upsert_opening
from tests.cli.helpers import env_for, fake_identifier, patch_digester, patch_extractor


def _fake_tavily_for(url: str) -> FakeTavily:
    return FakeTavily(
        fixtures={
            url: {
                "results": [{"url": url, "raw_content": "Synthetic job posting fixture."}],
                "failed_results": [],
            }
        }
    )


def _run_intake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    fake = _fake_tavily_for(url)
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(sequence=[[StopAction(reason="First pass done.")]]),
    )
    patch_digester(monkeypatch)
    result = CliRunner().invoke(
        cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"intake failed: {result.output}"


def _opening_id(tmp_path: Path) -> str:
    conn = sqlite3.connect(tmp_path / "screen.db")
    (opening_id,) = conn.execute("SELECT id FROM openings").fetchone()
    return str(opening_id)


def test_research_resumes_and_appends_new_trace_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.com/jobs/42"
    _run_intake(tmp_path, monkeypatch, url)
    opening_id = _opening_id(tmp_path)
    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, opening_id)
    assert opening is not None
    trace_path = tmp_path / "research_traces" / f"{opening.research_trace_id}.jsonl"
    events_before = trace_path.read_text(encoding="utf-8").splitlines()

    fetch_url = "https://levels.fyi/companies/acme"
    monkeypatch.setattr(
        cli_module,
        "_build_client",
        lambda: FakeBrowser(fetch_fixtures={fetch_url: {"raw_content": "Acme pays $400k TC."}}),
    )
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(
            sequence=[[FetchAction(url=fetch_url)], [StopAction(reason="Second pass done.")]]
        ),
    )
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research,
        [opening_id, "5"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"research failed: {result.output}"

    events_after = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(events_after) > len(events_before)
    extract_events = [
        json.loads(line) for line in events_after if json.loads(line)["tool"] == "tavily_extract"
    ]
    original_extracts = [e for e in extract_events if e["request"].get("urls") == [url]]
    assert len(original_extracts) == 1


def test_research_does_not_re_extract_original_page_into_assertions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.com/jobs/42"
    _run_intake(tmp_path, monkeypatch, url)
    opening_id = _opening_id(tmp_path)
    conn = sqlite3.connect(tmp_path / "screen.db")
    assertions_before = conn.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]

    monkeypatch.setattr(cli_module, "_build_client", FakeBrowser)
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(sequence=[[StopAction(reason="Nothing more to do.")]]),
    )
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research,
        [opening_id, "5"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"research failed: {result.output}"

    conn = sqlite3.connect(tmp_path / "screen.db")
    assertions_after = conn.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
    assert assertions_after == assertions_before


def test_research_stops_at_remaining_lifetime_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requesting more turns than the opening has left spends only the remainder."""
    url = "https://example.com/jobs/42"
    _run_intake(tmp_path, monkeypatch, url)
    opening_id = _opening_id(tmp_path)

    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, opening_id)
    assert opening is not None
    # Intake's initial page fetch already used 1 turn; leave exactly 1 more.
    upsert_opening(conn, opening.model_copy(update={"research_turns_budget": 2}))

    query = "Acme Corp staff engineer compensation 2024"
    monkeypatch.setattr(
        cli_module,
        "_build_client",
        lambda: FakeBrowser(search_fixtures={query: []}),
    )
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(
            sequence=[
                [SearchAction(query=query)],
                [StopAction(reason="Should not be reached.")],
            ]
        ),
    )
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.research,
        [opening_id, "5"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"research failed: {result.output}"
    assert "turn budget exhausted" in result.output


def test_research_no_remaining_budget_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.com/jobs/42"
    _run_intake(tmp_path, monkeypatch, url)
    opening_id = _opening_id(tmp_path)
    conn = connect(tmp_path / "screen.db")
    opening = get_opening(conn, opening_id)
    assert opening is not None
    upsert_opening(conn, opening.model_copy(update={"research_turns_budget": 0}))

    result = CliRunner().invoke(
        cli_module.research,
        [opening_id, "5"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"research failed: {result.output}"
    assert "no remaining" in result.output.lower()


def test_research_unknown_opening_raises_click_exception(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_module.research,
        ["no-such-opening", "5"],
        env=env_for(tmp_path),
    )
    assert result.exit_code != 0
    assert "no-such-opening" in result.output
