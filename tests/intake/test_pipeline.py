"""Pipeline behavior tests: URL in, DB rows + research trace out.

Calls `intake/pipeline.py` functions directly with injected fakes — no Click,
no CLI process, no filesystem fixtures beyond `tmp_path`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from screen.browser import BrowserError, TavilyBrowser
from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.intake import pipeline as pipeline_module
from screen.intake.fakes import FakeTavily
from screen.research.actions import FetchAction, StopAction
from screen.research.batch import RunDispatchDeps
from screen.research.fakes import FakeBrowser, FakePlanner
from tests.helpers import canned_assertion, fake_identifier


def _fake_tavily_for(url: str) -> FakeTavily:
    return FakeTavily(
        fixtures={
            url: {
                "results": [{"url": url, "raw_content": "Synthetic job posting fixture."}],
                "failed_results": [],
            }
        }
    )


def _default_planner() -> FakePlanner:
    return FakePlanner(sequence=[[StopAction(reason="All rubric dimensions addressed.")]])


def test_pipeline_writes_domain_rows_to_sqlite_not_json_files(tmp_path: Path) -> None:
    """The full pipeline fetches a URL and writes Company + Opening + Assertion rows to SQLite,
    not the retired company.json/opening.json/assertions.jsonl directory scheme."""
    url = "https://example.com/jobs/42"
    pipeline_module.intake_url(
        url,
        data_dir=tmp_path,
        client_factory=lambda: _fake_tavily_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=FakeDigester(["Synthetic digest."])
        ),
    )

    conn = sqlite3.connect(tmp_path / "screen.db")
    assert conn.execute("SELECT name FROM companies").fetchall() == [("Example Co",)]
    assert conn.execute("SELECT title FROM openings").fetchall() == [("Staff Engineer",)]
    assert conn.execute("SELECT target FROM assertions").fetchall() == [("stretch",)]
    assert list(tmp_path.rglob("company.json")) == []
    assert list(tmp_path.rglob("opening.json")) == []
    assert list(tmp_path.rglob("assertions.jsonl")) == []


def test_pipeline_records_partial_research_trace_on_failed_extract(tmp_path: Path) -> None:
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

    with pytest.raises(pipeline_module.IntakePipelineError):
        pipeline_module.intake_url(
            url,
            data_dir=tmp_path,
            client_factory=lambda: fake,
            identifier_factory=fake_identifier,
        )

    research_traces = list(tmp_path.rglob("*.jsonl"))
    assert len(research_traces) == 1
    lines = research_traces[0].read_text(encoding="utf-8").splitlines()
    parsed = json.loads(lines[0])
    assert parsed["response"]["failed_results"]


def test_pipeline_records_partial_research_trace_on_search_client_error(tmp_path: Path) -> None:
    """When `client.extract(...)` raises BrowserError, the pipeline writes a
    partial event and raises IntakePipelineError."""

    def _raise() -> TavilyBrowser:
        class _Broken(TavilyBrowser):
            def extract(self, urls):  # type: ignore[no-untyped-def]
                raise BrowserError("simulated transport failure")

        return _Broken(api_key="test")

    with pytest.raises(pipeline_module.IntakePipelineError):
        pipeline_module.intake_url(
            "https://example.com/jobs/42",
            data_dir=tmp_path,
            client_factory=_raise,
            identifier_factory=fake_identifier,
        )

    research_traces = list(tmp_path.rglob("*.jsonl"))
    assert len(research_traces) == 1
    lines = research_traces[0].read_text(encoding="utf-8").splitlines()
    parsed = json.loads(lines[0])
    assert "error" in parsed["response"]


def test_pipeline_returns_stop_reason(tmp_path: Path) -> None:
    """Pipeline output contains the stop reason emitted by the dispatcher."""
    url = "https://example.com/jobs/42"
    reason = pipeline_module.intake_url(
        url,
        data_dir=tmp_path,
        client_factory=lambda: _fake_tavily_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: RunDispatchDeps(
            planner=_default_planner(), digester=FakeDigester(["Synthetic digest."])
        ),
    )
    assert "All rubric dimensions addressed." in reason


def test_pipeline_dispatch_persists_fetch_assertions(tmp_path: Path) -> None:
    """Assertions added by the dispatch loop's own fetch actions are persisted
    to the DB, not just held in memory for the rest of the pass."""
    url = "https://example.com/jobs/42"
    fetch_url = "https://levels.fyi/companies/example-co"

    def _planner() -> FakePlanner:
        return FakePlanner(
            sequence=[
                [FetchAction(url=fetch_url)],
                [StopAction(reason="Second fetch done.")],
            ]
        )

    def _browser() -> FakeBrowser:
        return FakeBrowser(
            fetch_fixtures={
                url: {"raw_content": "Synthetic job posting fixture."},
                fetch_url: {"raw_content": "Example Co pays $400k TC."},
            }
        )

    pipeline_module.intake_url(
        url,
        data_dir=tmp_path,
        client_factory=lambda: _fake_tavily_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: RunDispatchDeps(
            planner=_planner(), browser=_browser(), digester=FakeDigester(["Synthetic digest."])
        ),
    )

    conn = sqlite3.connect(tmp_path / "screen.db")
    # FakeExtractor returns one assertion per call: one from the intake extraction,
    # one from the dispatch loop's own fetch of `fetch_url`.
    assert conn.execute("SELECT COUNT(*) FROM assertions").fetchone() == (2,)


def test_pipeline_intake_records_failure_details_in_trace(tmp_path: Path) -> None:
    """The initial intake URL failure remains fatal, but the recorded event
    carries BrowserError.details verbatim for the operator to inspect."""

    def _raise() -> TavilyBrowser:
        class _Broken(TavilyBrowser):
            def extract(self, urls):  # type: ignore[no-untyped-def]
                raise BrowserError("simulated transport failure", details={"exception": "boom"})

        return _Broken(api_key="test")

    with pytest.raises(pipeline_module.IntakePipelineError):
        pipeline_module.intake_url(
            "https://example.com/jobs/42",
            data_dir=tmp_path,
            client_factory=_raise,
            identifier_factory=fake_identifier,
        )

    research_traces = list(tmp_path.rglob("*.jsonl"))
    parsed = json.loads(research_traces[0].read_text(encoding="utf-8").splitlines()[0])
    assert parsed["response"]["details"] == {"exception": "boom"}


def test_pipeline_dispatch_continues_past_failed_fetch(tmp_path: Path) -> None:
    """A research-pass FetchAction that fails (no fixture, simulating a
    blocked/unfetchable page) does not abort the pipeline — the pass records
    the failure and continues to the planner's next action."""
    url = "https://example.com/jobs/42"
    blocked_url = "https://www.acmehealth.example/about/careers-list/blocked"

    def _planner() -> FakePlanner:
        return FakePlanner(
            sequence=[
                [FetchAction(url=blocked_url)],
                [StopAction(reason="Gave up after block.")],
            ]
        )

    reason = pipeline_module.intake_url(
        url,
        data_dir=tmp_path,
        client_factory=lambda: _fake_tavily_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: RunDispatchDeps(
            planner=_planner(), digester=FakeDigester(["Synthetic digest."])
        ),
    )

    assert "Gave up after block." in reason

    research_traces = list(tmp_path.rglob("*.jsonl"))
    lines = research_traces[0].read_text(encoding="utf-8").splitlines()
    failure_events = [json.loads(line) for line in lines if "error" in json.loads(line)["response"]]
    assert any(e["response"].get("details") for e in failure_events)
