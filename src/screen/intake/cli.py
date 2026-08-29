"""Click commands for the intake pipeline."""

import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import click

from screen.browser import (
    BrowserError,
    BrowserProtocol,
    TavilyBrowser,
)
from screen.digest.baml_digester import BAMLDigester
from screen.digest.protocol import DigesterProtocol
from screen.digest.service import update_digests_for_opening
from screen.extract.baml_extractor import BAMLExtractor
from screen.extract.extract import extract_assertions
from screen.extract.prompt import rubric_text_for_baml
from screen.extract.protocol import ExtractorProtocol
from screen.intake.baml_identifier import BAMLIdentifier
from screen.intake.company_id import derive_company_id
from screen.intake.events import ResearchTraceEvent, TavilyExtractResponse
from screen.intake.identify import IdentifierProtocol, identify_opening
from screen.intake.opening_id import derive_opening_id
from screen.intake.research_trace_id import derive_research_trace_id
from screen.intake.research_trace_io import append_line
from screen.paths import data_dir
from screen.research.baml_planner import BAMLPlanner
from screen.research.dispatcher import dispatch
from screen.research.protocol import PlannerProtocol
from screen.research.state import LoopState
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertions_for_opening,
    list_openings,
    upsert_company,
    upsert_opening,
)
from screen.types import Assertion, Company, IdentificationResult, Opening


def _db_path_for(data_dir: Path) -> Path:
    return data_dir / "screen.db"


def _build_client() -> BrowserProtocol:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    return TavilyBrowser(api_key=api_key or "test-stub-key")


def _build_identifier() -> IdentifierProtocol:
    return BAMLIdentifier()


def _build_extractor() -> ExtractorProtocol:
    return BAMLExtractor()


def _build_digester() -> DigesterProtocol:
    return BAMLDigester()


def _build_planner() -> PlannerProtocol:
    return BAMLPlanner()


def _noop_on_event(_event: object) -> None:
    """Placeholder on_event used until a real subscriber is injected."""


def _record_event(research_trace_path: Path, event: ResearchTraceEvent) -> None:
    append_line(research_trace_path, event.model_dump_json())


def _research_trace_path_for(data_dir: Path, research_trace_id: str) -> Path:
    return data_dir / "research_traces" / f"{research_trace_id}.jsonl"


def _read_page_content(research_trace_path: Path) -> tuple[str, str]:
    """Return (raw_content, url) from the first tavily_extract event."""
    if not research_trace_path.exists():
        raise click.ClickException(f"research trace missing at {research_trace_path}")
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
    raise click.ClickException(f"no tavily_extract event with raw_content in {research_trace_path}")


def _persist_company_and_opening(
    conn: sqlite3.Connection,
    identification: IdentificationResult,
    url: str,
    research_trace_id: str,
    now: datetime,
) -> tuple[Company, Opening]:
    company_id = derive_company_id(identification.company_name, url)
    opening_id = derive_opening_id(identification.opening_title, url)
    company = Company(
        id=company_id,
        name=identification.company_name,
        created_at=now,
    )
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


@click.command()
@click.argument("url")
def intake(url: str) -> None:
    """Fetch a job posting URL and persist Company + Opening + Assertion rows."""
    data_root = data_dir()
    client = _build_client()
    research_trace_path = _fetch_url(url, client, data_root)
    _identify_research_trace(research_trace_path, data_root)


@click.command()
def backfill_digests() -> None:
    """Warm the digest cache for every opening already in the DB — for use
    after a bulk import or a digest prompt change, not part of normal intake."""
    conn = connect(_db_path_for(data_dir()))
    openings = list_openings(conn)
    digester = _build_digester()
    rubric = rubric_text_for_baml()
    for opening in openings:
        update_digests_for_opening(
            conn,
            opening_id=opening.id,
            digester=digester,
            rubric_text=rubric,
            now=datetime.now(UTC),
        )
    click.echo(f"warmed digests for {len(openings)} opening(s)")


def _fetch_url(url: str, client: BrowserProtocol, data_dir: Path) -> Path:
    """Run the URL → research trace step. On transport failure, record the
    partial research trace and re-raise as a ClickException."""
    research_trace_id = derive_research_trace_id(url)
    research_trace_path = _research_trace_path_for(data_dir, research_trace_id)
    started = datetime.now(UTC)
    request_payload = {"urls": [url]}
    try:
        response = client.extract([url])
    except BrowserError as exc:
        event = ResearchTraceEvent(
            ts=started,
            tool="tavily_extract",
            request=request_payload,
            response={"error": str(exc)},
        )
        _record_event(research_trace_path, event)
        raise click.ClickException(f"intake failed for {url}: {exc}") from exc
    event = ResearchTraceEvent(
        ts=started,
        tool="tavily_extract",
        request=request_payload,
        response=dict(response),
    )
    _record_event(research_trace_path, event)
    return research_trace_path


def _identify_research_trace(research_trace_path: Path, data_dir: Path) -> None:
    """Run the research trace → Company + Opening + Assertions step."""
    page_content, url = _read_page_content(research_trace_path)
    identification = identify_opening(page_content, identifier=_build_identifier())
    research_trace_id = research_trace_path.stem
    conn = connect(_db_path_for(data_dir))
    company, opening = _persist_company_and_opening(
        conn, identification, url, research_trace_id, datetime.now(UTC)
    )
    click.echo(f"wrote company {company.id}")
    click.echo(f"wrote opening {opening.id}")
    all_assertions = _extract_assertions(conn, opening.id, page_content)
    _run_dispatch(
        conn,
        opening.id,
        url,
        all_assertions,
        company_id=company.id,
        page_content=page_content,
        company_name=identification.company_name,
        opening_title=identification.opening_title,
        on_event=lambda event: _record_event(research_trace_path, event),
    )


def _extract_assertions(
    conn: sqlite3.Connection,
    opening_id: str,
    chunk: str,
    *,
    extractor: ExtractorProtocol | None = None,
) -> list[Assertion]:
    """Extract assertions from `chunk`, append to the DB, return all for the opening.
    Returns existing + new so the caller can build LoopState without re-reading
    from disk.
    """
    existing = assertions_for_opening(conn, opening_id)

    rubric = rubric_text_for_baml()
    xt = extractor if extractor is not None else _build_extractor()
    new_assertions = extract_assertions(chunk, rubric, existing, extractor=xt)
    if new_assertions:
        append_assertions(conn, new_assertions, opening_id=opening_id)
    click.echo(f"wrote {len(new_assertions)} assertion(s) for opening {opening_id}")
    return existing + new_assertions


def _run_dispatch(
    conn: sqlite3.Connection,
    opening_id: str,
    url: str,
    assertions: list[Assertion],
    *,
    company_id: str,
    page_content: str,
    company_name: str,
    opening_title: str,
    planner: PlannerProtocol | None = None,
    browser: BrowserProtocol | None = None,
    extractor: ExtractorProtocol | None = None,
    digester: DigesterProtocol | None = None,
    on_event: Callable[..., None] | None = None,
) -> None:
    """Build LoopState from in-memory values and run one dispatch cycle.
    The CLI echoes the stop reason. No disk re-read: assertions list
    comes from the caller. Assertions the dispatch loop's own fetch actions
    add are not persisted here or by dispatch itself — unchanged from prior
    behavior, tracked by test_cli_dispatch_does_not_re_extract.
    """
    rubric = rubric_text_for_baml()
    state = LoopState(
        opening_id=opening_id,
        company_id=company_id,
        company_name=company_name,
        opening_title=opening_title,
        page_content=page_content,
        url=url,
        rubric_text=rubric,
        assertions=assertions,
        search_budget=int(os.environ.get("SCREEN_SEARCH_BUDGET", "5")),
        searches_used=0,
        token_budget=int(os.environ.get("SCREEN_TOKEN_BUDGET", "50000")),
        tokens_used=0,
    )
    pl = planner if planner is not None else _build_planner()
    br = browser if browser is not None else _build_client()
    xt = extractor if extractor is not None else _build_extractor()
    dg = digester if digester is not None else _build_digester()
    ev_callback: Callable[..., None] = on_event if on_event is not None else _noop_on_event
    summary = dispatch(state, planner=pl, browser=br, extractor=xt, on_event=ev_callback)
    click.echo(f"pass complete: {summary.stopped_reason}")
    update_digests_for_opening(
        conn,
        opening_id=opening_id,
        digester=dg,
        rubric_text=rubric,
        now=datetime.now(UTC),
    )
