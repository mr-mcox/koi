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
from screen.paths import data_dir
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
    list_openings,
    upsert_company,
    upsert_dimension_ruling,
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


def _build_planner(config: ScoringConfig | None = None) -> PlannerProtocol:
    return BAMLPlanner(config=config)


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
    *,
    research_turns_budget: int,
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
        research_turns_budget=research_turns_budget,
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


@click.command()
def backfill_research_turns_budget() -> None:
    """Reset every opening's research_turns_budget to the current scoring.yaml value.

    A blanket reset, not a fill-if-zero: existing openings created before this dial
    existed default to 0 (migration 0006); openings with a manually bumped budget are
    reset too, same as intake seeding a new opening (F23).
    """
    conn = connect(_db_path_for(data_dir()))
    openings = list_openings(conn)
    budget = load_scoring_config().research_turns_budget
    for opening in openings:
        upsert_opening(conn, opening.model_copy(update={"research_turns_budget": budget}))
    click.echo(f"set research_turns_budget={budget} for {len(openings)} opening(s)")


@click.command()
def backfill_dimension_ruling_covered_assertion_ids() -> None:
    """Reset every `DimensionRuling`'s `covered_assertion_ids` to the assertions currently
    filed under its target, for rulings that predate the field (migration 0007).

    A blanket reset, not a fill-if-empty: this approximates each pin's snapshot as "every
    assertion under the target as of the backfill run" rather than "as of the pin's own
    `created_at`" — the exact historical set isn't reconstructable once new assertions
    have already landed, and this is the correction path for that. Manually re-running
    it (e.g. after this command itself) overwrites again, same pattern as
    `backfill-research-turns-budget` (dimension-ruling-drift bearing Done When).
    """
    conn = connect(_db_path_for(data_dir()))
    openings = list_openings(conn)
    updated = 0
    for opening in openings:
        assertion_ids_by_target: dict[str, list[str]] = {}
        for a in assertions_for_opening(conn, opening.id):
            assertion_ids_by_target.setdefault(a.target, []).append(a.id)
        for ruling in dimension_rulings_for_opening(conn, opening.id):
            covered = assertion_ids_by_target.get(ruling.target, [])
            upsert_dimension_ruling(
                conn, ruling.model_copy(update={"covered_assertion_ids": covered})
            )
            updated += 1
    click.echo(f"backfilled covered_assertion_ids for {updated} dimension ruling(s)")


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
            response={"error": str(exc), "details": exc.details},
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
        conn,
        identification,
        url,
        research_trace_id,
        datetime.now(UTC),
        research_turns_budget=load_scoring_config().research_turns_budget,
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
    turn_budget: int | None = None,
    turns_used: int = 0,
    visited_urls: list[str] | None = None,
    prior_queries: list[str] | None = None,
    planner: PlannerProtocol | None = None,
    browser: BrowserProtocol | None = None,
    extractor: ExtractorProtocol | None = None,
    digester: DigesterProtocol | None = None,
    on_event: Callable[..., None] | None = None,
) -> None:
    """Build LoopState from in-memory values and run one dispatch cycle.
    The CLI echoes the stop reason. No disk re-read: assertions list
    comes from the caller. Assertions the dispatch loop's own fetch actions
    add are persisted immediately via `append_assertions`, one fetch at a
    time, so a pass interrupted mid-loop still keeps what it found.
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
    pl = planner if planner is not None else _build_planner()
    br = browser if browser is not None else _build_client()
    xt = extractor if extractor is not None else _build_extractor()
    dg = digester if digester is not None else _build_digester()
    ev_callback: Callable[..., None] = on_event if on_event is not None else _noop_on_event

    def _persist_assertions(new_assertions: list[Assertion]) -> None:
        append_assertions(conn, new_assertions, opening_id=opening_id)

    summary = dispatch(
        state,
        planner=pl,
        deps=DispatchDeps(
            browser=br,
            extractor=xt,
            on_event=ev_callback,
            on_assertions=_persist_assertions,
        ),
        scoring_config=scoring_config,
    )
    click.echo(f"pass complete: {summary.stopped_reason}")
    update_digests_for_opening(
        conn,
        opening_id=opening_id,
        digester=dg,
        rubric_text=rubric,
        now=datetime.now(UTC),
    )


@click.group()
def cli() -> None:
    """Scaffolding entry point for the migration/backfill commands
    (`backfill-research-turns-budget`, `backfill-digests`,
    `backfill-dimension-ruling-covered-assertion-ids`) that aren't wired
    into the stable `python -m screen` / `./run` surface.
    `intake` stays reachable both here and via `python -m screen` —
    `screen/__main__.py` is the stable single-command surface; this group is
    the temporary one for everything else.
    """


cli.add_command(intake)
cli.add_command(backfill_digests)
cli.add_command(backfill_research_turns_budget)
cli.add_command(backfill_dimension_ruling_covered_assertion_ids)

if __name__ == "__main__":
    cli()
