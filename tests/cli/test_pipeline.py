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
from screen.research.actions import FetchAction, StopAction
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.score.loader import load_scoring_config
from tests.cli.helpers import (
    env_for,
    fake_identifier,
    patch_digester,
    patch_extractor,
    patch_planner,
)


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
    patch_digester(monkeypatch)

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


def test_cli_seeds_research_turns_budget_from_scoring_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """intake seeds Opening.research_turns_budget from scoring.yaml, not a literal."""
    url = "https://example.com/jobs/42"
    fake = _fake_tavily_for(url)
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_planner(monkeypatch)
    patch_digester(monkeypatch)

    result = CliRunner().invoke(
        cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = sqlite3.connect(tmp_path / "screen.db")
    budget = conn.execute("SELECT research_turns_budget FROM openings").fetchone()
    assert budget == (load_scoring_config().research_turns_budget,)


def test_cli_records_partial_research_trace_on_failed_extract(
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
    research_traces = list(tmp_path.rglob("*.jsonl"))
    assert len(research_traces) == 1
    lines = research_traces[0].read_text(encoding="utf-8").splitlines()
    parsed = json.loads(lines[0])
    assert parsed["response"]["failed_results"]


def test_cli_records_partial_research_trace_on_search_client_error(
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
    research_traces = list(tmp_path.rglob("*.jsonl"))
    assert len(research_traces) == 1
    lines = research_traces[0].read_text(encoding="utf-8").splitlines()
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
    patch_digester(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0, f"CLI failed:\n{result.output}"
    assert (
        "All rubric dimensions addressed." in result.output
    ), f"Stop reason not in CLI output. Got:\n{result.output}"


def test_cli_dispatch_persists_fetch_assertions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assertions added by the dispatch loop's own fetch actions are persisted
    to the DB, not just held in memory for the rest of the pass."""
    url = "https://example.com/jobs/42"
    fake = _fake_tavily_for(url)
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    fetch_url = "https://levels.fyi/companies/example-co"
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(
            sequence=[
                [FetchAction(url=fetch_url)],
                [StopAction(reason="Second fetch done.")],
            ]
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "_build_client",
        lambda: FakeBrowser(
            fetch_fixtures={
                url: {"raw_content": "Synthetic job posting fixture."},
                fetch_url: {"raw_content": "Example Co pays $400k TC."},
            }
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = sqlite3.connect(tmp_path / "screen.db")
    # FakeExtractor returns one assertion per call: one from the intake extraction,
    # one from the dispatch loop's own fetch of `fetch_url`.
    assert conn.execute("SELECT COUNT(*) FROM assertions").fetchone() == (2,)


def test_cli_intake_records_failure_details_in_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The initial intake URL failure remains fatal, but the recorded event
    carries BrowserError.details verbatim for the operator to inspect."""

    def _raise(self, urls):  # type: ignore[no-untyped-def]
        raise BrowserError("simulated transport failure", details={"exception": "boom"})

    monkeypatch.setattr(TavilyBrowser, "extract", _raise)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.intake,
        ["https://example.com/jobs/42"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    research_traces = list(tmp_path.rglob("*.jsonl"))
    parsed = json.loads(research_traces[0].read_text(encoding="utf-8").splitlines()[0])
    assert parsed["response"]["details"] == {"exception": "boom"}


def test_cli_dispatch_continues_past_failed_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A research-pass FetchAction that fails (no fixture, simulating a
    blocked/unfetchable page) does not abort the pipeline — the pass records
    the failure and continues to the planner's next action."""
    url = "https://example.com/jobs/42"
    fake = _fake_tavily_for(url)
    monkeypatch.setattr(TavilyBrowser, "extract", lambda self, urls: fake.extract(urls))
    monkeypatch.setattr(cli_module, "_build_identifier", fake_identifier)
    patch_extractor(monkeypatch)
    patch_digester(monkeypatch)

    blocked_url = "https://www.acmehealth.example/about/careers-list/blocked"
    monkeypatch.setattr(
        cli_module,
        "_build_planner",
        lambda: FakePlanner(
            sequence=[
                [FetchAction(url=blocked_url)],
                [StopAction(reason="Gave up after block.")],
            ]
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "_build_client",
        lambda: FakeBrowser(
            fetch_fixtures={url: {"raw_content": "Synthetic job posting fixture."}}
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.intake, [url], env=env_for(tmp_path), catch_exceptions=False)
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "Gave up after block." in result.output

    research_traces = list(tmp_path.rglob("*.jsonl"))
    lines = research_traces[0].read_text(encoding="utf-8").splitlines()
    failure_events = [json.loads(line) for line in lines if "error" in json.loads(line)["response"]]
    assert any(e["response"].get("details") for e in failure_events)
