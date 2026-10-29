"""Pipeline behavior tests: URL in, DB rows + research trace out.

Calls `intake/pipeline.py` functions directly with injected fakes — no Click,
no CLI process, no filesystem fixtures beyond `tmp_path`.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from screen.browser import BrowserError, SearchHit, TavilyBrowser
from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.intake import pipeline as pipeline_module
from screen.research.actions import FetchAction, StopAction
from screen.research.fakes import FakeBrowser, FakePlanner
from screen.research_trace.ids import derive_research_trace_id
from screen.research_trace.trace_io import read_page_content, research_trace_path_for
from tests.helpers import canned_assertion, fake_dispatch_deps, fake_extractor, fake_identifier


def _fetcher_for(url: str) -> FakeBrowser:
    return FakeBrowser(fetch_fixtures={url: {"raw_content": "Synthetic job posting fixture."}})


class _FailingFetcher:
    """Raises the given BrowserError on every fetch."""

    def __init__(self, error: BrowserError) -> None:
        self._error = error

    def fetch(self, url: str) -> SearchHit:
        raise self._error


def _default_planner() -> FakePlanner:
    return FakePlanner(sequence=[[StopAction(reason="All rubric dimensions addressed.")]])


def test_pipeline_writes_domain_rows_to_sqlite_not_json_files(tmp_path: Path) -> None:
    """The full pipeline fetches a URL and writes Company + Opening + Assertion rows to SQLite,
    not the retired company.json/opening.json/assertions.jsonl directory scheme."""
    url = "https://example.com/jobs/42"
    pipeline_module.intake_url(
        url,
        data_dir=tmp_path,
        client_factory=lambda: _fetcher_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: fake_dispatch_deps(
            planner=_default_planner(), digester=FakeDigester(["Synthetic digest."])
        ),
    )

    conn = sqlite3.connect(tmp_path / "screen.db")
    assert conn.execute("SELECT name FROM companies").fetchall() == [("Example Co",)]
    assert conn.execute("SELECT title FROM openings").fetchall() == [("Staff Engineer",)]
    assert conn.execute("SELECT target FROM assertions").fetchall() == [("craft_direction",)]
    assert list(tmp_path.rglob("company.json")) == []
    assert list(tmp_path.rglob("opening.json")) == []
    assert list(tmp_path.rglob("assertions.jsonl")) == []


def test_pipeline_records_partial_research_trace_on_failed_extract(tmp_path: Path) -> None:
    """Regression: a failed Tavily extraction is an HTTP 200 with empty
    `results`. Recording that as a page deferred the error three stages, to
    "no tavily_extract event with raw_content" — a message naming a file
    instead of a cause.
    """
    url = "https://nowhere.example/"

    class _GoneClient:
        """Tavily SDK stand-in: every extraction fails with an HTTP 200."""

        def extract(self, **_kwargs: object) -> dict[str, object]:
            return {"results": [], "failed_results": [{"url": url, "error": "fake says: gone"}]}

    browser = TavilyBrowser(api_key="test", client=cast(Any, _GoneClient()), sleep=lambda _s: None)

    with pytest.raises(pipeline_module.IntakePipelineError) as excinfo:
        pipeline_module.intake_url(
            url,
            data_dir=tmp_path,
            client_factory=lambda: browser,
            identifier_factory=fake_identifier,
            extractor_factory=fake_extractor,
            deps_factory=fake_dispatch_deps,
        )

    assert excinfo.value.stage == "fetch_url"
    research_traces = list(tmp_path.rglob("*.jsonl"))
    assert len(research_traces) == 1
    lines = research_traces[0].read_text(encoding="utf-8").split("\n")
    parsed = json.loads(lines[0])
    assert parsed["response"]["details"]["failed_results"]


def test_pipeline_retries_a_transient_fetch_failure(tmp_path: Path) -> None:
    """Regression: intake called `extract` directly, bypassing the retry the
    research path already had.
    """
    url = "https://example.com/job/1"

    class _FlakyClient:
        """Tavily SDK stand-in: fails the first extraction, then succeeds."""

        def __init__(self) -> None:
            self.calls = 0

        def extract(self, **_kwargs: object) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                return {
                    "results": [],
                    "failed_results": [{"url": url, "error": "Failed to fetch url"}],
                }
            return {
                "results": [{"url": url, "raw_content": "Synthetic posting body."}],
                "failed_results": [],
            }

    sdk = _FlakyClient()
    browser = TavilyBrowser(
        api_key="test",
        client=cast(Any, sdk),
        sleep=lambda _s: None,
    )

    pipeline_module.fetch_url(url, browser, tmp_path)

    assert sdk.calls == 2
    content, recorded_url = read_page_content(
        research_trace_path_for(tmp_path, derive_research_trace_id(url))
    )
    assert content == "Synthetic posting body."
    assert recorded_url == url


def test_pipeline_returns_stop_reason(tmp_path: Path) -> None:
    """Pipeline output contains the stop reason emitted by the dispatcher."""
    url = "https://example.com/jobs/42"
    reason = pipeline_module.intake_url(
        url,
        data_dir=tmp_path,
        client_factory=lambda: _fetcher_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: fake_dispatch_deps(
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
        client_factory=lambda: _fetcher_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: fake_dispatch_deps(
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

    with pytest.raises(pipeline_module.IntakePipelineError):
        pipeline_module.intake_url(
            "https://example.com/jobs/42",
            data_dir=tmp_path,
            client_factory=lambda: _FailingFetcher(
                BrowserError("simulated transport failure", details={"exception": "boom"})
            ),
            identifier_factory=fake_identifier,
            extractor_factory=fake_extractor,
            deps_factory=fake_dispatch_deps,
        )

    research_traces = list(tmp_path.rglob("*.jsonl"))
    parsed = json.loads(research_traces[0].read_text(encoding="utf-8").splitlines()[0])
    assert parsed["response"]["error"] == "simulated transport failure"
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
        client_factory=lambda: _fetcher_for(url),
        identifier_factory=fake_identifier,
        extractor_factory=lambda: FakeExtractor([[canned_assertion()]]),
        deps_factory=lambda: fake_dispatch_deps(
            planner=_planner(), digester=FakeDigester(["Synthetic digest."])
        ),
    )

    assert "Gave up after block." in reason

    research_traces = list(tmp_path.rglob("*.jsonl"))
    lines = research_traces[0].read_text(encoding="utf-8").splitlines()
    failure_events = [json.loads(line) for line in lines if "error" in json.loads(line)["response"]]
    assert any(e["response"].get("details") for e in failure_events)
