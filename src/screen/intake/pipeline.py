"""Click-independent intake pipeline: URL -> research trace -> Company + Opening +
Assertions + one research-dispatch pass.

The web intake-queue worker calls this directly (no `click.ClickException`
in the call chain), the same way `research/batch.py` is a Click-independent
module the web batch route calls. Every stage raises `IntakePipelineError`
(with a `.stage` name): a queue worker needs to catch a failure, record
*which stage* failed, and move on to the next queued URL.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from screen.browser import BrowserError, BrowserProtocol
from screen.digest.protocol import DigesterProtocol
from screen.extract.extract import extract_assertions
from screen.extract.prompt import rubric_text_for_baml
from screen.extract.protocol import ExtractorProtocol
from screen.intake.baml_identifier import BAMLIdentifier
from screen.intake.company_id import derive_company_id
from screen.intake.events import ResearchTraceEvent
from screen.intake.identify import IdentifierProtocol, identify_opening
from screen.intake.opening_id import derive_opening_id
from screen.intake.research_trace_id import derive_research_trace_id
from screen.paths import data_dir as _data_dir
from screen.research.batch import (
    ResearchTraceMissingError,
    build_client,
    build_digester,
    build_extractor,
    build_planner,
    read_page_content,
    record_event,
    research_trace_path_for,
    run_dispatch,
)
from screen.research.protocol import PlannerProtocol
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertions_for_opening,
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


def build_identifier() -> IdentifierProtocol:
    return BAMLIdentifier()


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
    try:
        page_content, url = read_page_content(research_trace_path)
    except ResearchTraceMissingError as exc:
        raise IntakePipelineError("read_page_content", str(exc)) from exc
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
