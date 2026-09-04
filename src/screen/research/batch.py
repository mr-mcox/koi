"""Click-independent research batch engine.

Extracted from `intake/cli.py` so the web route can schedule research turns
via `fastapi.BackgroundTasks` without a Click dependency.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np

from screen.browser import BrowserProtocol, TavilyBrowser
from screen.digest.baml_digester import BAMLDigester
from screen.digest.protocol import DigesterProtocol
from screen.digest.service import update_digests_for_opening
from screen.extract.baml_extractor import BAMLExtractor
from screen.extract.prompt import (
    all_constraint_slugs,
    all_dimension_slugs,
    all_non_scoring_slugs,
    rubric_text_for_baml,
)
from screen.extract.protocol import ExtractorProtocol
from screen.intake.events import ResearchTraceEvent, TavilyExtractResponse
from screen.intake.research_trace_io import append_line
from screen.intake.research_trace_replay import replay_research_trace
from screen.research.baml_planner import BAMLPlanner
from screen.research.dispatcher import DispatchDeps, dispatch
from screen.research.protocol import PlannerProtocol
from screen.research.state import LoopState
from screen.score.bandit import aggregate_uncertainty, draw_opening
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertion_rulings_for_opening,
    assertions_for_opening,
    dimension_rulings_for_opening,
    get_company,
    get_opening,
    list_openings,
)
from screen.types import Assertion, Fit, Opening


class NoSuchOpeningError(RuntimeError):
    """Raised when an opening id doesn't exist in the DB."""


class ResearchTraceMissingError(RuntimeError):
    """Raised when an opening's research trace file is missing or has no
    tavily_extract event with raw_content."""


def build_client() -> BrowserProtocol:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    return TavilyBrowser(api_key=api_key or "test-stub-key")


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


def research_trace_path_for(data_root: Path, research_trace_id: str) -> Path:
    return data_root / "research_traces" / f"{research_trace_id}.jsonl"


def read_page_content(research_trace_path: Path) -> tuple[str, str]:
    """Return (raw_content, url) from the first tavily_extract event."""
    if not research_trace_path.exists():
        raise ResearchTraceMissingError(f"research trace missing at {research_trace_path}")
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
    raise ResearchTraceMissingError(
        f"no tavily_extract event with raw_content in {research_trace_path}"
    )


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
    update_digests: Callable[..., None] = update_digests_for_opening,
) -> str:
    """Build LoopState from in-memory values and run one dispatch cycle.
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
            browser=br,
            extractor=xt,
            on_event=ev_callback,
            on_assertions=_persist_assertions,
        ),
        scoring_config=scoring_config,
    )
    update_digests(
        conn,
        opening_id=opening_id,
        digester=dg,
        rubric_text=rubric,
        now=datetime.now(UTC),
    )
    return summary.stopped_reason


def resume_opening(
    conn: sqlite3.Connection,
    data_root: Path,
    opening: Opening,
    turns_requested: int,
    *,
    planner: PlannerProtocol | None = None,
    browser: BrowserProtocol | None = None,
    extractor: ExtractorProtocol | None = None,
    digester: DigesterProtocol | None = None,
) -> int:
    """Resume one opening's research from its trace, spending at most
    `min(turns_requested, remaining lifetime budget)` turns. Returns the
    number of turns actually spent.
    """
    company = get_company(conn, opening.company_id)
    if company is None:  # pragma: no cover — FK constraint on openings.company_id
        raise NoSuchOpeningError(f"no company with id {opening.company_id!r}")
    research_trace_path = research_trace_path_for(data_root, opening.research_trace_id)
    page_content, url = read_page_content(research_trace_path)
    replay = replay_research_trace(research_trace_path)
    remaining = max(opening.research_turns_budget - replay.turns_used, 0)
    to_spend = min(turns_requested, remaining)
    if to_spend <= 0:
        return 0

    assertions = assertions_for_opening(conn, opening.id)
    run_dispatch(
        conn,
        opening.id,
        url,
        assertions,
        company_id=company.id,
        page_content=page_content,
        company_name=company.name,
        opening_title=opening.title,
        turn_budget=replay.turns_used + to_spend,
        turns_used=replay.turns_used,
        visited_urls=replay.visited_urls,
        prior_queries=replay.prior_queries,
        planner=planner,
        browser=browser,
        extractor=extractor,
        digester=digester,
        on_event=lambda event: record_event(research_trace_path, event),
    )
    turns_used_after = replay_research_trace(research_trace_path).turns_used
    return turns_used_after - replay.turns_used


def remaining_budget(data_root: Path, opening: Opening) -> int:
    research_trace_path = research_trace_path_for(data_root, opening.research_trace_id)
    turns_used = replay_research_trace(research_trace_path).turns_used
    return max(opening.research_turns_budget - turns_used, 0)


def opening_weight(conn: sqlite3.Connection, opening: Opening, config: ScoringConfig) -> float:
    """Aggregate remaining uncertainty for one opening, assembled the same way
    `get_queue` assembles rulings for scoring — the latest ruling per
    assertion id, one `DimensionRuling` pin per target."""
    assertions = assertions_for_opening(conn, opening.id)
    rulings: dict[str, Fit] = {
        ruling.assertion_id: ruling.fit
        for ruling in assertion_rulings_for_opening(conn, opening.id)
    }
    dimension_rulings = {
        ruling.target: ruling for ruling in dimension_rulings_for_opening(conn, opening.id)
    }
    return aggregate_uncertainty(assertions, config, rulings, dimension_rulings)


def eligible_weights(
    conn: sqlite3.Connection, data_root: Path, config: ScoringConfig
) -> dict[str, float]:
    """Every opening with remaining `research_turns_budget` headroom, mapped to its
    current aggregate-uncertainty weight. Recomputed fresh on every call — the caller
    redraws from this after each turn so a just-spent turn's new assertions immediately
    affect the next draw."""
    return {
        opening.id: opening_weight(conn, opening, config)
        for opening in list_openings(conn)
        if remaining_budget(data_root, opening) > 0
    }


@dataclass
class DrawEvent:
    """One turn's draw, reported for tracing (CLI echo, web progress dict)."""

    opening_id: str
    draw_probability: float
    rank_before: int
    rank_after: int


@dataclass
class BatchProgress:
    """Mutable progress state shared between the background worker and the
    polling web route. Single-uvicorn-worker assumption; not persisted."""

    total: int
    spent: int = 0
    current_opening_id: str | None = None
    touched: list[str] = field(default_factory=list)
    running: bool = True


def _draw_event(
    weights: dict[str, float], opening_id: str, weights_after: dict[str, float]
) -> DrawEvent:
    draw_weight = weights[opening_id]
    draw_probability = draw_weight / sum(weights.values())
    rank_before = sorted(weights.values(), reverse=True).index(draw_weight) + 1
    after_weight = weights_after.get(opening_id, 0.0)
    ranked_after = sorted(weights_after.values(), reverse=True)
    rank_after = (
        ranked_after.index(after_weight) + 1 if opening_id in weights_after else len(weights)
    )
    return DrawEvent(opening_id, draw_probability, rank_before, rank_after)


def _run_batch_turn(
    conn: sqlite3.Connection,
    data_root: Path,
    cfg: ScoringConfig,
    weights: dict[str, float],
    rng: np.random.Generator,
    *,
    touched: list[str],
    progress: MutableMapping[str, object] | None,
    planner_factory: Callable[[], PlannerProtocol] | None,
    planner: PlannerProtocol | None,
    browser: BrowserProtocol | None,
    extractor: ExtractorProtocol | None,
    digester: DigesterProtocol | None,
) -> tuple[str, int, DrawEvent] | None:
    """Draw one opening, spend one turn, and return the draw event.
    Returns `None` when the planner stopped without spending a turn.
    """
    opening_id = draw_opening(weights, rng)
    opening = cast(Opening, get_opening(conn, opening_id))
    if progress is not None:
        progress["current_opening_id"] = opening_id
    turn_planner = planner_factory() if planner_factory is not None else planner
    spent = resume_opening(
        conn,
        data_root,
        opening,
        1,
        planner=turn_planner,
        browser=browser,
        extractor=extractor,
        digester=digester,
    )
    if spent == 0:
        return None
    if opening_id not in touched:
        touched.append(opening_id)
    weights_after = eligible_weights(conn, data_root, cfg)
    return opening_id, spent, _draw_event(weights, opening_id, weights_after)


def _begin_progress(progress: MutableMapping[str, object] | None, batch_size: int) -> None:
    if progress is not None:
        progress["total"] = batch_size
        progress["running"] = True


def _end_progress(
    progress: MutableMapping[str, object] | None,
    total_spent: int,
    touched: list[str],
) -> None:
    if progress is not None:
        progress["spent"] = total_spent
        progress["touched"] = touched
        progress["running"] = False
        progress["current_opening_id"] = None


def run_batch(
    conn: sqlite3.Connection,
    data_root: Path,
    batch_size: int,
    progress: MutableMapping[str, object] | None = None,
    *,
    config: ScoringConfig | None = None,
    planner_factory: Callable[[], PlannerProtocol] | None = None,
    planner: PlannerProtocol | None = None,
    browser: BrowserProtocol | None = None,
    extractor: ExtractorProtocol | None = None,
    digester: DigesterProtocol | None = None,
    on_draw: Callable[[DrawEvent], None] | None = None,
) -> tuple[int, list[str]]:
    """Spend up to `batch_size` turns, one per draw, weighted by each eligible opening's
    aggregate remaining uncertainty. The draw is seeded from `config.seed`, so a batch run
    against an unchanged DB snapshot reproduces the same sequence of draws.

    Returns (total_turns_spent, touched_opening_ids). `progress` is updated in place so
    a polling web route can observe `spent`, `current_opening_id`, and `touched` while
    the batch runs. `on_draw`, if given, is called once per spent turn with the
    `DrawEvent` — a hook for draw-level tracing (test assertions on draw order today).

    `planner_factory` is called once per turn; the planner is stateful in the test fakes.
    `planner` (a single instance) is supported for direct callers but will be rebuilt each
    turn if `planner_factory` is provided.
    """
    cfg = config if config is not None else load_scoring_config()
    rng = np.random.default_rng(cfg.seed)
    touched: list[str] = []
    total_spent = 0
    _begin_progress(progress, batch_size)
    for _ in range(batch_size):
        weights = eligible_weights(conn, data_root, cfg)
        if not weights:
            break
        turn = _run_batch_turn(
            conn,
            data_root,
            cfg,
            weights,
            rng,
            touched=touched,
            progress=progress,
            planner_factory=planner_factory,
            planner=planner,
            browser=browser,
            extractor=extractor,
            digester=digester,
        )
        if turn is None:
            continue
        opening_id, spent, draw_event = turn
        total_spent += spent
        if progress is not None:
            progress["spent"] = total_spent
            progress["touched"] = touched
        if on_draw is not None:
            on_draw(draw_event)
    _end_progress(progress, total_spent, touched)
    return total_spent, touched


def opening_research_status(data_root: Path, opening: Opening) -> tuple[int, int]:
    """Return (turns_used, budget) for one opening, mirroring the retired
    `research-status` CLI output."""
    research_trace_path = research_trace_path_for(data_root, opening.research_trace_id)
    turns_used = replay_research_trace(research_trace_path).turns_used
    return turns_used, opening.research_turns_budget


@dataclass
class BatchEngine:
    """Seam for the web route: holds the factories so tests can inject fakes."""

    planner_factory: Callable[[], PlannerProtocol] = field(default=build_planner)
    browser_factory: Callable[[], BrowserProtocol] = field(default=build_client)
    extractor_factory: Callable[[], ExtractorProtocol] = field(default=build_extractor)
    digester_factory: Callable[[], DigesterProtocol] = field(default=build_digester)

    def run(
        self,
        db_path: Path,
        batch_size: int,
        progress: MutableMapping[str, object],
    ) -> None:
        """Open a dedicated connection and run the batch. Meant for
        `fastapi.BackgroundTasks`; the request that scheduled it has already
        returned.
        """
        data_root = db_path.parent
        conn = connect(db_path)
        try:
            run_batch(
                conn,
                data_root,
                batch_size,
                progress,
                planner_factory=self.planner_factory,
                browser=self.browser_factory(),
                extractor=self.extractor_factory(),
                digester=self.digester_factory(),
            )
        finally:
            conn.close()
