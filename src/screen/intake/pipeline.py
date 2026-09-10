"""Click-independent intake pipeline: URL -> research trace -> Company + Opening +
Assertions + one research-dispatch pass.

The web intake-queue worker calls this directly (no `click.ClickException`
in the call chain), the same way `research/batch.py` is a Click-independent
module the web batch route calls. Every stage raises `IntakePipelineError`
(with a `.stage` name): a queue worker needs to catch a failure, record
*which stage* failed, and move on to the next queued URL.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from screen.browser import BrowserError, BrowserProtocol, TavilyBrowser
from screen.digest.baml_digester import BAMLDigester
from screen.digest.protocol import DigesterProtocol
from screen.digest.service import update_digests_for_opening
from screen.extract.baml_extractor import BAMLExtractor
from screen.extract.extract import extract_assertions
from screen.extract.prompt import (
    all_constraint_slugs,
    all_dimension_slugs,
    all_non_scoring_slugs,
    rubric_text_for_baml,
)
from screen.extract.protocol import ExtractorProtocol
from screen.intake.baml_identifier import BAMLIdentifier
from screen.intake.company_id import derive_company_id
from screen.intake.events import ResearchTraceEvent, TavilyExtractResponse
from screen.intake.identify import IdentifierProtocol, identify_opening
from screen.intake.opening_id import derive_opening_id
from screen.intake.research_trace_id import derive_research_trace_id
from screen.intake.research_trace_io import append_line
from screen.paths import data_dir as _data_dir
from screen.research.baml_planner import BAMLPlanner
from screen.research.dispatcher import DispatchDeps, dispatch
from screen.research.protocol import PlannerProtocol
from screen.research.state import LoopState
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertions_for_opening,
    dimension_rulings_for_opening,
    upsert_company,
    upsert_opening,
)
from screen.types import Assertion, Company, IdentificationResult, Opening


class IntakePipelineError(RuntimeError):
    """Raised by any pipeline stage. `stage` names which one, so a caller
    processing many URLs (the queue worker) can record it and continue."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


def db_path_for(data_dir: Path) -> Path:
    return data_dir / "screen.db"


def build_client() -> BrowserProtocol:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    return TavilyBrowser(api_key=api_key or "test-stub-key")


def build_identifier() -> IdentifierProtocol:
    return BAMLIdentifier()


def build_extractor() -> ExtractorProtocol:
    return BAMLExtractor()


def build_digester() -> DigesterProtocol:
    return BAMLDigester()


def build_planner(config: ScoringConfig | None = None) -> PlannerProtocol:
    return BAMLPlanner(config=config)


def _noop_on_event(_event: object) -> None:
    """Placeholder on_event used until a real subscriber is injected."""


def record_event(research_trace_path: Path, event: ResearchTraceEvent) -> None:
    append_line(research_trace_path, event.model_dump_json())


def research_trace_path_for(data_dir: Path, research_trace_id: str) -> Path:
    return data_dir / "research_traces" / f"{research_trace_id}.jsonl"


def read_page_content(research_trace_path: Path) -> tuple[str, str]:
    """Return (raw_content, url) from the first tavily_extract event."""
    if not research_trace_path.exists():
        raise IntakePipelineError(
            "read_page_content", f"research trace missing at {research_trace_path}"
        )
    for raw_line in research_trace_path.read_text(encoding="utf-8").splitlines():
        if not raw_line:
            continue
        event = ResearchTraceEvent.model_validate_json(raw_line)
        if event.tool != "tavily_extract":
            continue
        response = cast(TavilyExtractResponse, event.response)
        results = response.get("results") or []
        if not results:
            continue
        first = results[0]
        url = first.get("url") or (event.request.get("urls") or [""])[0]
        raw_content = first.get("raw_content", "")
        return str(raw_content), str(url)
    raise IntakePipelineError(
        "read_page_content", f"no tavily_extract event with raw_content in {research_trace_path}"
    )


def persist_company_and_opening(
    conn: sqlite3.Connection,
    identification: IdentificationResult,
    url: str,
    research_trace_id: str,
    now: datetime,
    *,
    research_turns_budget: int,
) -> tuple[Company, Opening]:
    company_id = derive_company_id(identification.company_name, url)
    opening_id = derive_opening_id(identification.opening_title, url)
    company = Company(id=company_id, name=identification.company_name, created_at=now)
    opening = Opening(
        id=opening_id,
        company_id=company_id,
        title=identification.opening_title,
        url=url,
        research_trace_id=research_trace_id,
        research_turns_budget=research_turns_budget,
        created_at=now,
    )
    upsert_company(conn, company)
    upsert_opening(conn, opening)
    return company, opening


def fetch_url(url: str, client: BrowserProtocol, data_dir: Path) -> Path:
    """Run the URL -> research trace step. On transport failure, record the
    partial research trace and re-raise as an `IntakePipelineError`."""
    research_trace_id = derive_research_trace_id(url)
    research_trace_path = research_trace_path_for(data_dir, research_trace_id)
    started = datetime.now(UTC)
    request_payload = {"urls": [url]}
    try:
        response = client.extract([url])
    except BrowserError as exc:
        event = ResearchTraceEvent(
            ts=started,
            tool="tavily_extract",
            request=request_payload,
            response={"error": str(exc), "details": exc.details},
        )
        record_event(research_trace_path, event)
        raise IntakePipelineError("fetch_url", f"intake failed for {url}: {exc}") from exc
    event = ResearchTraceEvent(
        ts=started, tool="tavily_extract", request=request_payload, response=dict(response)
    )
    record_event(research_trace_path, event)
    return research_trace_path


def extract_and_persist_assertions(
    conn: sqlite3.Connection,
    opening_id: str,
    chunk: str,
    *,
    extractor: ExtractorProtocol | None = None,
) -> list[Assertion]:
    """Extract assertions from `chunk`, append to the DB, return existing + new
    for the opening — the caller builds `LoopState` from this without a re-read."""
    existing = assertions_for_opening(conn, opening_id)
    rubric = rubric_text_for_baml()
    xt = extractor if extractor is not None else build_extractor()
    new_assertions = extract_assertions(chunk, rubric, existing, extractor=xt)
    if new_assertions:
        append_assertions(conn, new_assertions, opening_id=opening_id)
    return existing + new_assertions


def run_dispatch(
    conn: sqlite3.Connection,
    opening_id: str,
    url: str,
    assertions: list[Assertion],
    *,
    company_id: str,
    page_content: str,
    company_name: str,
    opening_title: str,
    turn_budget: int | None = None,
    turns_used: int = 0,
    visited_urls: list[str] | None = None,
    prior_queries: list[str] | None = None,
    planner: PlannerProtocol | None = None,
    browser: BrowserProtocol | None = None,
    extractor: ExtractorProtocol | None = None,
    digester: DigesterProtocol | None = None,
    on_event: Callable[..., None] | None = None,
) -> str:
    """Build `LoopState` from in-memory values and run one dispatch cycle.
    Returns the stop reason. No disk re-read: assertions list comes from the
    caller. Assertions the dispatch loop's own fetch actions add are persisted
    immediately via `append_assertions`, one fetch at a time, so a pass
    interrupted mid-loop still keeps what it found.
    """
    rubric = rubric_text_for_baml()
    scoring_config = load_scoring_config()
    rulings = {ruling.target: ruling for ruling in dimension_rulings_for_opening(conn, opening_id)}
    targets = all_dimension_slugs() + all_constraint_slugs() + all_non_scoring_slugs()
    state = LoopState(
        opening_id=opening_id,
        company_id=company_id,
        company_name=company_name,
        opening_title=opening_title,
        page_content=page_content,
        url=url,
        rubric_text=rubric,
        assertions=assertions,
        turn_budget=(
            turn_budget
            if turn_budget is not None
            else int(os.environ.get("SCREEN_TURN_BUDGET", scoring_config.research_turns_budget))
        ),
        turns_used=turns_used,
        visited_urls=visited_urls or [],
        prior_queries=prior_queries or [],
        rulings=rulings,
        targets=targets,
        active_target_action_cap=scoring_config.research_target_action_cap,
    )
    pl = planner if planner is not None else build_planner()
    br = browser if browser is not None else build_client()
    xt = extractor if extractor is not None else build_extractor()
    dg = digester if digester is not None else build_digester()
    ev_callback: Callable[..., None] = on_event if on_event is not None else _noop_on_event

    def _persist_assertions(new_assertions: list[Assertion]) -> None:
        append_assertions(conn, new_assertions, opening_id=opening_id)

    summary = dispatch(
        state,
        planner=pl,
        deps=DispatchDeps(
            browser=br, extractor=xt, on_event=ev_callback, on_assertions=_persist_assertions
        ),
        scoring_config=scoring_config,
    )
    update_digests_for_opening(
        conn, opening_id=opening_id, digester=dg, rubric_text=rubric, now=datetime.now(UTC)
    )
    return summary.stopped_reason


def identify_research_trace(
    research_trace_path: Path,
    data_dir: Path,
    *,
    identifier_factory: Callable[[], IdentifierProtocol] = build_identifier,
    extractor_factory: Callable[[], ExtractorProtocol] = build_extractor,
    planner_factory: Callable[[], PlannerProtocol] = build_planner,
    browser_factory: Callable[[], BrowserProtocol] = build_client,
    digester_factory: Callable[[], DigesterProtocol] = build_digester,
) -> str:
    """Run the research trace -> Company + Opening + Assertions step. Returns
    the dispatch stop reason (the CLI echoes it; the queue worker ignores it).
    Takes factories, not built instances: the extractor/planner/etc. are each
    built twice in the pipeline (once for the intake extraction, again inside
    `run_dispatch`'s own fetch actions) and a `FakeExtractor` advances its
    canned-result cursor per call, so sharing one instance across both call
    sites would starve the second of results a real BAML client wouldn't.
    """
    page_content, url = read_page_content(research_trace_path)
    identification = identify_opening(page_content, identifier=identifier_factory())
    research_trace_id = research_trace_path.stem
    conn = connect(db_path_for(data_dir))
    company, opening = persist_company_and_opening(
        conn,
        identification,
        url,
        research_trace_id,
        datetime.now(UTC),
        research_turns_budget=load_scoring_config().research_turns_budget,
    )
    all_assertions = extract_and_persist_assertions(
        conn, opening.id, page_content, extractor=extractor_factory()
    )
    return run_dispatch(
        conn,
        opening.id,
        url,
        all_assertions,
        company_id=company.id,
        page_content=page_content,
        company_name=identification.company_name,
        opening_title=identification.opening_title,
        planner=planner_factory(),
        browser=browser_factory(),
        extractor=extractor_factory(),
        digester=digester_factory(),
        on_event=lambda event: record_event(research_trace_path, event),
    )


# π This is a lot of factories. Are they all independent or do some of them share enough responsibility that they ought to be combined? Or is this intake_url trying to do too much?
def intake_url(
    url: str,
    data_dir: Path | None = None,
    *,
    client_factory: Callable[[], BrowserProtocol] = build_client,
    identifier_factory: Callable[[], IdentifierProtocol] = build_identifier,
    extractor_factory: Callable[[], ExtractorProtocol] = build_extractor,
    planner_factory: Callable[[], PlannerProtocol] = build_planner,
    browser_factory: Callable[[], BrowserProtocol] | None = None,
    digester_factory: Callable[[], DigesterProtocol] = build_digester,
) -> str:
    """Run the full pipeline for one URL: fetch, identify, persist, dispatch.
    Returns the dispatch stop reason. Raises `IntakePipelineError` on failure
    at any stage — the caller (CLI command or queue worker) decides what to
    do with a failed URL.
    queue worker uses the defaults.
    """
    data_root = data_dir if data_dir is not None else _data_dir()
    client = client_factory()
    research_trace_path = fetch_url(url, client, data_root)
    return identify_research_trace(
        research_trace_path,
        data_root,
        identifier_factory=identifier_factory,
        extractor_factory=extractor_factory,
        planner_factory=planner_factory,
        browser_factory=browser_factory if browser_factory is not None else client_factory,
        digester_factory=digester_factory,
    )
