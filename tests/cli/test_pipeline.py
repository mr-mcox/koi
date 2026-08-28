"""End-to-end `intake` pipeline tests: URL in, DB rows out, via `CliRunner`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from screen.browser import BrowserError, TavilyBrowser
from screen.intake import cli as cli_module
from screen.intake.fakes import FakeTavily
from tests.cli.helpers import env_for, fake_identifier, patch_extractor, patch_planner


def _fake_tavily_for(url: str) -> FakeTavily:
    return FakeTavily(
        fixtures={
            url: {
                "results": [{"url": url, "raw_content": "Synthetic job posting fixture."}],
                "failed_results": [],
            }
        }
    )


def test_cli_writes_domain_rows_to_sqlite_not_json_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full pipeline fetches a URL and writes Company + Opening + Assertion rows to SQLite,
    not the retired company.json/opening.json/assertions.jsonl directory scheme."""
    url = "https://example.com/jobs/42"
    fake = _fake_tavily_for(url)
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)

    result = CliRunner().invoke(
        cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = sqlite3.connect(tmp_path / "screen.db")
    assert conn.execute("SELECT name FROM companies").fetchall() == [("Example Co",)]
    assert conn.execute("SELECT title FROM openings").fetchall() == [("Staff Engineer",)]
    assert conn.execute("SELECT target FROM assertions").fetchall() == [("stretch",)]
    assert list(tmp_path.rglob("company.json")) == []
    assert list(tmp_path.rglob("opening.json")) == []
    assert list(tmp_path.rglob("assertions.jsonl")) == []


def test_cli_records_partial_transcript_on_failed_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `extract` returns failed_results, the pipeline writes the partial event
    and exits non-zero. Error type classification is not built yet."""
    url = "https://nowhere.example/"
    fake = FakeTavily(
        fixtures={
            url: {
                "results": [],
                "failed_results": [{"url": url, "error": "fake says: gone"}],
            }
        }
    )
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False)
    assert result.exit_code != 0
    transcripts = list(tmp_path.rglob("*.jsonl"))
    assert len(transcripts) == 1
    lines = transcripts[0].read_text(encoding="utf-8").splitlines()
    parsed = json.loads(lines[0])
    assert parsed["response"]["failed_results"]


def test_cli_records_partial_transcript_on_search_client_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `client.extract(...)` raises BrowserError, the pipeline writes a
    partial event and exits non-zero via ClickException."""

    def _raise(self, urls):  # type: ignore[no-untyped-def]
        raise BrowserError("simulated transport failure")

    monkeypatch.setattr(TavilyBrowser, "extract", _raise)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.intake,
        ["https://example.com/jobs/42"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    transcripts = list(tmp_path.rglob("*.jsonl"))
    assert len(transcripts) == 1
    lines = transcripts[0].read_text(encoding="utf-8").splitlines()
    parsed = json.loads(lines[0])
    assert "error" in parsed["response"]


def test_cli_echoes_stop_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI output contains the stop reason emitted by the dispatcher."""
    url = "https://example.com/jobs/42"
    fake = _fake_tavily_for(url)
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0, f"CLI failed:\n{result.output}"
    assert (
        "All rubric dimensions addressed." in result.output
    ), f"Stop reason not in CLI output. Got:\n{result.output}"


def test_cli_dispatch_does_not_re_extract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatch does not persist more assertions: row count is unchanged after dispatch."""
    url = "https://example.com/jobs/42"
    fake = _fake_tavily_for(url)
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0
    conn = sqlite3.connect(tmp_path / "screen.db")
    # FakeExtractor returned exactly one assertion; dispatch must not add more.
    assert conn.execute("SELECT COUNT(*) FROM assertions").fetchone() == (1,)
