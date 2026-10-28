"""Click-independent intake pipeline: URL -> research trace -> Company + Opening +
Assertions + one research-dispatch pass.

The web intake-queue worker calls this directly (no `click.ClickException`
in the call chain), the same way `research/batch.py` is a Click-independent
module the web batch route calls. Every stage raises `IntakePipelineError`
(with a `.stage` name): a queue worker needs to catch a failure, record
*which stage* failed, and move on to the next queued URL.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from screen.browser import BrowserError, BrowserProtocol
from screen.extract.extract import extract_assertions
from screen.extract.protocol import ExtractorProtocol
from screen.intake.company_id import derive_company_id
from screen.intake.events import ResearchTraceEvent
from screen.intake.identify import IdentifierProtocol, identify_opening
from screen.intake.opening_id import derive_opening_id
from screen.intake.research_trace_id import derive_research_trace_id
from screen.research.batch import (
    INTAKE_FIRST_PASS_TURN_BUDGET,
    ResearchTraceMissingError,
    RunDispatchDeps,
    read_page_content,
    record_event,
    research_trace_path_for,
    run_dispatch,
)
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
    processing many URLs (the queue worker) can record it and continue.

    `permanent` is True when re-running the URL provably cannot succeed. It is
    advisory: the queue still offers a retry, because calling a posting dead
    is the operator's judgment, not the pipeline's.
    """

    def __init__(self, stage: str, message: str, *, permanent: bool = False) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.permanent = permanent


def db_path_for(data_dir: Path) -> Path:
    return data_dir / "screen.db"


def persist_company_and_opening(
    conn: sqlite3.Connection,
    identification: IdentificationResult,
    url: str,
    research_trace_id: str,
    now: datetime,
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
        created_at=now,
    )
    upsert_company(conn, company)
    upsert_opening(conn, opening)
    return company, opening


def fetch_url(url: str, client: BrowserProtocol, data_dir: Path) -> Path:
    """Run the URL -> research trace step. On fetch failure, record the
    partial research trace and re-raise as an `IntakePipelineError`.

    Goes through `fetch`, not `extract`: a failed extraction is an HTTP 200
    with empty results, which `extract` returns and `fetch` raises on. `fetch`
    also carries the retry.
    """
    research_trace_id = derive_research_trace_id(url)
    research_trace_path = research_trace_path_for(data_dir, research_trace_id)
    started = datetime.now(UTC)
    request_payload = {"urls": [url]}
    try:
        hit = client.fetch(url)
    except BrowserError as exc:
        event = ResearchTraceEvent(
            ts=started,
            tool="tavily_extract",
            request=request_payload,
            response={"error": str(exc), "details": exc.details, "results": []},
        )
        record_event(research_trace_path, event)
        raise IntakePipelineError(
            "fetch_url",
            f"intake failed for {url}: {exc}",
            permanent=exc.permanent,
        ) from exc
    event = ResearchTraceEvent(
        ts=started,
        tool="tavily_extract",
        request=request_payload,
        response={"results": [dict(hit)], "failed_results": []},
    )
    record_event(research_trace_path, event)
    return research_trace_path


def extract_and_persist_assertions(
    conn: sqlite3.Connection,
    opening_id: str,
    chunk: str,
    *,
    extractor: ExtractorProtocol,
    rubric_text: str,
) -> list[Assertion]:
    """Extract assertions from `chunk`, append to the DB, return existing + new
    for the opening — the caller builds `LoopState` from this without a re-read."""
    existing = assertions_for_opening(conn, opening_id)
    new_assertions = extract_assertions(chunk, rubric_text, existing, extractor=extractor)
    if new_assertions:
        append_assertions(conn, new_assertions, opening_id=opening_id)
    return existing + new_assertions


def identify_research_trace(
    research_trace_path: Path,
    data_dir: Path,
    *,
    identifier_factory: Callable[[], IdentifierProtocol],
    extractor_factory: Callable[[], ExtractorProtocol],
    deps_factory: Callable[[], RunDispatchDeps],
    turn_budget: int = INTAKE_FIRST_PASS_TURN_BUDGET,
) -> str:
    """Run the research trace -> Company + Opening + Assertions step. Returns
    the dispatch stop reason (the CLI echoes it; the queue worker ignores it).

    `extractor_factory` is called twice: once for the intake extraction pass,
    again for `run_dispatch`'s own fetch actions. A `FakeExtractor` advances
    its canned-result cursor per call, so sharing one instance across both
    call sites would starve the second of results a real BAML client
    wouldn't. `deps_factory` supplies the dispatch loop's other collaborators
    (planner, browser, digester); its `extractor` field is overridden below.
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
    )
    base_deps = deps_factory()
    all_assertions = extract_and_persist_assertions(
        conn,
        opening.id,
        page_content,
        extractor=extractor_factory(),
        rubric_text=base_deps.rubric.full(),
    )
    deps = dataclasses.replace(
        base_deps,
        extractor=extractor_factory(),
        on_event=lambda event: record_event(research_trace_path, event),
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
        turn_budget=turn_budget,
        deps=deps,
    )


def intake_url(
    url: str,
    data_dir: Path,
    *,
    client_factory: Callable[[], BrowserProtocol],
    identifier_factory: Callable[[], IdentifierProtocol],
    extractor_factory: Callable[[], ExtractorProtocol],
    deps_factory: Callable[[], RunDispatchDeps],
    turn_budget: int = INTAKE_FIRST_PASS_TURN_BUDGET,
) -> str:
    """Run the full pipeline for one URL: fetch, identify, persist, dispatch.
    Returns the dispatch stop reason. Raises `IntakePipelineError` on failure
    at any stage — the caller (web route or queue worker) decides what to do
    with a failed URL.
    """
    research_trace_path = fetch_url(url, client_factory(), data_dir)
    return identify_research_trace(
        research_trace_path,
        data_dir,
        identifier_factory=identifier_factory,
        extractor_factory=extractor_factory,
        deps_factory=deps_factory,
        turn_budget=turn_budget,
    )
