"""Unit tests for `_identify_research_trace` — the research trace → Company + Opening +
Assertions step, called directly rather than through `CliRunner`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import click
import pytest

from screen.intake import cli as cli_module
from screen.intake.cli import _identify_research_trace
from screen.intake.fakes import FakeIdentifier
from screen.store.db import connect
from screen.store.repo import assertions_for_opening
from screen.types import IdentificationResult
from tests.cli.helpers import fake_identifier, patch_extractor, patch_planner, seed_research_trace


def test_identify_research_trace_writes_company_and_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_identify_research_trace` reads the research trace, calls the identifier, and writes the records."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic page content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_research_trace(research_trace_path, tmp_path)

    conn = sqlite3.connect(tmp_path / "screen.db")
    companies = conn.execute("SELECT name FROM companies").fetchall()
    openings = conn.execute("SELECT title, research_trace_id FROM openings").fetchall()
    assert companies == [("Example Co",)]
    assert openings == [("Staff Engineer", "abcdef0123456789")]


def test_identify_research_trace_leaves_trace_at_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The research trace file is never moved: it already lives at its final path
    (data/research_traces/<research_trace_id>.jsonl), addressed via Opening.research_trace_id."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_research_trace(research_trace_path, tmp_path)
    assert research_trace_path.exists()


def test_identify_research_trace_records_decide_plan_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop's dispatch pass wires on_event to the research trace file, not the
    no-op default — decide_plan events must land alongside tavily_extract."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_research_trace(research_trace_path, tmp_path)
    tools = [
        json.loads(line)["tool"]
        for line in research_trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert "decide_plan" in tools


def test_identify_research_trace_ignores_sibling_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sibling file in the research traces directory must survive untouched."""
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "x", "https://example.com/jobs/42")
    sibling = research_trace_path.parent / "research_notes.md"
    sibling.write_text("private", encoding="utf-8")
    monkeypatch.setattr(cli_module, "_build_identifier", lambda: fake_identifier(title="Eng"))
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_research_trace(research_trace_path, tmp_path)
    assert research_trace_path.exists()
    assert sibling.exists()


def test_identify_research_trace_raises_when_trace_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare id with no research trace file emits a ClickException."""
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    with pytest.raises(click.ClickException) as exc_info:
        _identify_research_trace(
            tmp_path / "research_traces" / "no-such-research_trace.jsonl", tmp_path
        )
    assert "research trace missing" in exc_info.value.message.lower()


def test_identify_research_trace_skips_blank_and_non_tavily_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank lines and non-tavily events are skipped; the first tavily_extract with raw_content wins."""
    research_trace = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    research_trace.parent.mkdir(parents=True)
    url = "https://example.com/jobs/42"
    research_trace.write_text(
        "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_search",
                "request": {"query": "x"},
                "response": {"results": [], "failed_results": []},
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:01Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {
                    "results": [{"url": url, "raw_content": "real content"}],
                    "failed_results": [],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_module,
        "_build_identifier",
        lambda: FakeIdentifier(
            [IdentificationResult(company_name="Example", opening_title="Eng", opening_notes="n")]
        ),
    )
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)

    _identify_research_trace(research_trace, tmp_path)
    conn = sqlite3.connect(tmp_path / "screen.db")
    assert conn.execute("SELECT title FROM openings").fetchall() == [("Eng",)]


def test_identify_research_trace_errors_when_no_tavily_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A research trace with only non-tavily events produces a ClickException."""
    research_trace = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    research_trace.parent.mkdir(parents=True)
    research_trace.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_search",
                "request": {"query": "x"},
                "response": {"results": [], "failed_results": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)

    with pytest.raises(click.ClickException) as exc_info:
        _identify_research_trace(research_trace, tmp_path)
    assert "no tavily_extract" in exc_info.value.message.lower()


def test_identify_research_trace_writes_assertions_to_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After _identify_research_trace, at least one valid Assertion exists in the DB for the opening."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic page content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_research_trace(research_trace_path, tmp_path)

    conn = connect(tmp_path / "screen.db")
    (opening_id,) = conn.execute("SELECT id FROM openings").fetchone()
    assertions = assertions_for_opening(conn, opening_id)
    assert len(assertions) >= 1, "at least one assertion must be persisted"
    parsed = assertions[0]
    assert parsed.target in [
        "stretch",
        "peer",
        "trajectory",
        "mission",
        "agentic",
        "compensation",
        "domain",
        "location",
        "internal_culture",
        "extractive_business",
        "non_scoring:obtainability",
    ]
    assert len(parsed.citations) >= 1


def test_identify_research_trace_errors_on_event_with_empty_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tavily_extract event with empty results treats the research trace as missing content."""
    research_trace = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    research_trace.parent.mkdir(parents=True)
    research_trace.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": ["https://example.com/jobs/42"]},
                "response": {"results": [], "failed_results": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)

    with pytest.raises(click.ClickException) as exc_info:
        _identify_research_trace(research_trace, tmp_path)
    assert "no tavily_extract" in exc_info.value.message.lower()
