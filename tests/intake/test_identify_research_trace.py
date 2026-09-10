"""Unit tests for `identify_research_trace` — the research trace → Company + Opening +
Assertions step, called directly rather than through Click.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.intake.fakes import FakeIdentifier
from screen.intake.pipeline import IntakePipelineError, identify_research_trace
from screen.research.actions import StopAction
from screen.research.batch import RunDispatchDeps
from screen.research.fakes import FakePlanner
from screen.store.db import connect
from screen.store.repo import assertions_for_opening
from screen.types import IdentificationResult
from tests.helpers import canned_assertion, fake_identifier, seed_research_trace


def _default_planner() -> FakePlanner:
    return FakePlanner(sequence=[[StopAction(reason="All rubric dimensions addressed.")]])


def _default_extractor() -> FakeExtractor:
    return FakeExtractor([[canned_assertion()]])


def _default_digester() -> FakeDigester:
    return FakeDigester(["Synthetic digest."])


def test_identify_research_trace_writes_company_and_opening(tmp_path: Path) -> None:
    """`identify_research_trace` reads the research trace, calls the identifier, and writes the records."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic page content.", url)
    identify_research_trace(
        research_trace_path,
        tmp_path,
        identifier_factory=fake_identifier,
        extractor_factory=_default_extractor,
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=_default_digester()
        ),
    )

    conn = sqlite3.connect(tmp_path / "screen.db")
    companies = conn.execute("SELECT name FROM companies").fetchall()
    openings = conn.execute("SELECT title, research_trace_id FROM openings").fetchall()
    assert companies == [("Example Co",)]
    assert openings == [("Staff Engineer", "abcdef0123456789")]


def test_identify_research_trace_leaves_trace_at_final_path(tmp_path: Path) -> None:
    """The research trace file is never moved: it already lives at its final path
    (data/research_traces/<research_trace_id>.jsonl), addressed via Opening.research_trace_id."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic content.", url)
    identify_research_trace(
        research_trace_path,
        tmp_path,
        identifier_factory=fake_identifier,
        extractor_factory=_default_extractor,
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=_default_digester()
        ),
    )
    assert research_trace_path.exists()


def test_identify_research_trace_records_decide_plan_event(tmp_path: Path) -> None:
    """The loop's dispatch pass wires on_event to the research trace file, not the
    no-op default — decide_plan events must land alongside tavily_extract."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic content.", url)
    identify_research_trace(
        research_trace_path,
        tmp_path,
        identifier_factory=fake_identifier,
        extractor_factory=_default_extractor,
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=_default_digester()
        ),
    )
    tools = [
        json.loads(line)["tool"]
        for line in research_trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert "decide_plan" in tools


def test_identify_research_trace_ignores_sibling_files(tmp_path: Path) -> None:
    """A sibling file in the research traces directory must survive untouched."""
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "x", "https://example.com/jobs/42")
    sibling = research_trace_path.parent / "research_notes.md"
    sibling.write_text("private", encoding="utf-8")
    identify_research_trace(
        research_trace_path,
        tmp_path,
        identifier_factory=lambda: fake_identifier(title="Eng"),
        extractor_factory=_default_extractor,
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=_default_digester()
        ),
    )
    assert research_trace_path.exists()
    assert sibling.exists()


def test_identify_research_trace_raises_when_trace_missing(tmp_path: Path) -> None:
    """A bare id with no research trace file raises IntakePipelineError."""
    with pytest.raises(IntakePipelineError) as exc_info:
        identify_research_trace(
            tmp_path / "research_traces" / "no-such-research_trace.jsonl",
            tmp_path,
            identifier_factory=fake_identifier,
        )
    assert "research trace missing" in str(exc_info.value).lower()


def test_identify_research_trace_skips_blank_and_non_tavily_lines(tmp_path: Path) -> None:
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

    identify_research_trace(
        research_trace,
        tmp_path,
        identifier_factory=lambda: FakeIdentifier(
            [IdentificationResult(company_name="Example", opening_title="Eng", opening_notes="n")]
        ),
        extractor_factory=_default_extractor,
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=_default_digester()
        ),
    )
    conn = sqlite3.connect(tmp_path / "screen.db")
    assert conn.execute("SELECT title FROM openings").fetchall() == [("Eng",)]


def test_identify_research_trace_errors_when_no_tavily_extract(tmp_path: Path) -> None:
    """A research trace with only non-tavily events raises IntakePipelineError."""
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

    with pytest.raises(IntakePipelineError) as exc_info:
        identify_research_trace(
            research_trace,
            tmp_path,
            identifier_factory=fake_identifier,
        )
    assert "no tavily_extract" in str(exc_info.value).lower()


def test_identify_research_trace_writes_assertions_to_db(tmp_path: Path) -> None:
    """After `identify_research_trace`, at least one valid Assertion exists in the DB for the opening."""
    url = "https://example.com/jobs/42"
    research_trace_path = tmp_path / "research_traces" / "abcdef0123456789.jsonl"
    seed_research_trace(research_trace_path, "Synthetic page content.", url)
    identify_research_trace(
        research_trace_path,
        tmp_path,
        identifier_factory=fake_identifier,
        extractor_factory=_default_extractor,
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=_default_digester()
        ),
    )

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


def test_identify_research_trace_errors_on_event_with_empty_results(tmp_path: Path) -> None:
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

    with pytest.raises(IntakePipelineError) as exc_info:
        identify_research_trace(
            research_trace,
            tmp_path,
            identifier_factory=fake_identifier,
        )
    assert "no tavily_extract" in str(exc_info.value).lower()
