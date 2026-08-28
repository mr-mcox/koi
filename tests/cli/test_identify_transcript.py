"""Unit tests for `_identify_transcript` — the transcript → Company + Opening +
Assertions step, called directly rather than through `CliRunner`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import click
import pytest

from screen.intake import cli as cli_module
from screen.intake.cli import _identify_transcript
from screen.intake.fakes import FakeIdentifier
from screen.store.db import connect
from screen.store.repo import assertions_for_opening
from screen.types import IdentificationResult
from tests.cli.helpers import fake_identifier, patch_extractor, patch_planner, seed_transcript


def test_identify_transcript_writes_company_and_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_identify_transcript` reads the transcript, calls the identifier, and writes the records."""
    url = "https://example.com/jobs/42"
    transcript_path = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    seed_transcript(transcript_path, "Synthetic page content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_transcript(transcript_path, tmp_path)

    conn = sqlite3.connect(tmp_path / "screen.db")
    companies = conn.execute("SELECT name FROM companies").fetchall()
    openings = conn.execute("SELECT title, transcript_id FROM openings").fetchall()
    assert companies == [("Example Co",)]
    assert openings == [("Staff Engineer", "abcdef0123456789")]


def test_identify_transcript_leaves_transcript_at_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transcript file is never moved: it already lives at its final path
    (data/transcripts/<transcript_id>.jsonl), addressed via Opening.transcript_id."""
    url = "https://example.com/jobs/42"
    transcript_path = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    seed_transcript(transcript_path, "Synthetic content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_transcript(transcript_path, tmp_path)
    assert transcript_path.exists()


def test_identify_transcript_records_decide_plan_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop's dispatch pass wires on_event to the transcript file, not the
    no-op default — decide_plan events must land alongside tavily_extract."""
    url = "https://example.com/jobs/42"
    transcript_path = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    seed_transcript(transcript_path, "Synthetic content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_transcript(transcript_path, tmp_path)
    tools = [
        json.loads(line)["tool"]
        for line in transcript_path.read_text(encoding="utf-8").splitlines()
    ]
    assert "decide_plan" in tools


def test_identify_transcript_ignores_sibling_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sibling file in the transcripts directory must survive untouched."""
    transcript_path = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    seed_transcript(transcript_path, "x", "https://example.com/jobs/42")
    sibling = transcript_path.parent / "research_notes.md"
    sibling.write_text("private", encoding="utf-8")
    monkeypatch.setattr(cli_module, "_build_identifier", lambda: fake_identifier(title="Eng"))
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_transcript(transcript_path, tmp_path)
    assert transcript_path.exists()
    assert sibling.exists()


def test_identify_transcript_raises_when_transcript_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare id with no transcript file emits a ClickException."""
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    with pytest.raises(click.ClickException) as exc_info:
        _identify_transcript(tmp_path / "transcripts" / "no-such-transcript.jsonl", tmp_path)
    assert "transcript missing" in exc_info.value.message.lower()


def test_identify_transcript_skips_blank_and_non_tavily_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank lines and non-tavily events are skipped; the first tavily_extract with raw_content wins."""
    transcript = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    transcript.parent.mkdir(parents=True)
    url = "https://example.com/jobs/42"
    transcript.write_text(
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

    _identify_transcript(transcript, tmp_path)
    conn = sqlite3.connect(tmp_path / "screen.db")
    assert conn.execute("SELECT title FROM openings").fetchall() == [("Eng",)]


def test_identify_transcript_errors_when_no_tavily_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transcript with only non-tavily events produces a ClickException."""
    transcript = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
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
        _identify_transcript(transcript, tmp_path)
    assert "no tavily_extract" in exc_info.value.message.lower()


def test_identify_transcript_writes_assertions_to_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After _identify_transcript, at least one valid Assertion exists in the DB for the opening."""
    url = "https://example.com/jobs/42"
    transcript_path = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    seed_transcript(transcript_path, "Synthetic page content.", url)
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    _identify_transcript(transcript_path, tmp_path)

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


def test_identify_transcript_errors_on_event_with_empty_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tavily_extract event with empty results treats the transcript as missing content."""
    transcript = tmp_path / "transcripts" / "abcdef0123456789.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
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
        _identify_transcript(transcript, tmp_path)
    assert "no tavily_extract" in exc_info.value.message.lower()
