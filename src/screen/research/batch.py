"""Research batch engine: schedules research turns via `fastapi.BackgroundTasks`."""

from __future__ import annotations

import dataclasses
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np

from screen.browser import BrowserProtocol
from screen.digest.protocol import DigesterProtocol
from screen.digest.service import update_digests_for_opening
from screen.extract.prompt import (
    RubricText,
    all_dimension_slugs,
)
from screen.extract.protocol import ExtractorProtocol
from screen.pool import rank_screening_pool
from screen.research.dispatcher import DispatchDeps, dispatch
from screen.research.protocol import PlannerProtocol
from screen.research.state import LoopState
from screen.research_trace.replay import TraceReplay, replay_research_trace
from screen.research_trace.trace_io import read_page_content, record_event, research_trace_path_for
from screen.score.bandit import aggregate_uncertainty, boundary_weight, draw_opening
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertion_rulings_for_opening,
    assertions_for_opening,
    get_company,
    get_opening,
    list_openings,
)
from screen.types import Assertion, Fit, Opening


class NoSuchOpeningError(RuntimeError):
    """Raised when an opening id doesn't exist in the DB."""


@dataclass
class ResumeResult:
    """What `resume_opening` spent and why it stopped."""

    turns_spent: int
    stopped_reason: str


def _noop_on_event(_event: object) -> None:
    """Default `on_event`. The trace path is known only per opening, so each pass
    replaces this with a recorder bound to its own trace."""


@dataclass
class RunDispatchDeps:
    """`run_dispatch`'s collaborators, bundled the way `DispatchDeps` bundles
    the dispatch loop's own effect ports — so a new one touches this type
    instead of `run_dispatch`'s signature and every call site that relays it.
    Production instances come from `screen.wiring`."""

    planner: PlannerProtocol
    browser: BrowserProtocol
    extractor: ExtractorProtocol
    digester: DigesterProtocol
    rubric: RubricText
    on_event: Callable[..., None] = field(default=_noop_on_event)
    update_digests: Callable[..., None] = field(default=update_digests_for_opening)


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
    turn_budget: int,
    deps: RunDispatchDeps,
    resume: TraceReplay | None = None,
) -> str:
    """Build LoopState from in-memory values and run one dispatch cycle.
    Returns the stop reason. No disk re-read: assertions list comes from the
    caller. Assertions the dispatch loop's own fetch actions add are persisted
    immediately via `append_assertions`, one fetch at a time, so a pass
    interrupted mid-loop still keeps what it found.

    `resume` carries the turns/urls/queries already spent on a prior pass
    (from `replay_research_trace`); omitted for a fresh pass, which starts
    at zero. `turn_budget` is the total turns the trace may reach, prior passes
    included.
    """
    rubric = deps.rubric.full()
    scoring_config = load_scoring_config()
    targets = all_dimension_slugs()
    replay = (
        resume
        if resume is not None
        else TraceReplay(turns_used=0, visited_urls=[], prior_queries=[], target_stalls={})
    )
    state = LoopState(
        opening_id=opening_id,
        company_id=company_id,
        company_name=company_name,
        opening_title=opening_title,
        page_content=page_content,
        url=url,
        rubric_text=rubric,
        assertions=assertions,
        turn_budget=turn_budget,
        turns_used=replay.turns_used,
        visited_urls=replay.visited_urls,
        prior_queries=replay.prior_queries,
        targets=targets,
        active_target_action_cap=scoring_config.research_block_turns,
        target_stall_counts=replay.target_stalls,
    )

    def _persist_assertions(new_assertions: list[Assertion]) -> None:
        append_assertions(conn, new_assertions, opening_id=opening_id)

    summary = dispatch(
        state,
        planner=deps.planner,
        deps=DispatchDeps(
            browser=deps.browser,
            extractor=deps.extractor,
            on_event=deps.on_event,
            on_assertions=_persist_assertions,
        ),
        scoring_config=scoring_config,
    )
    deps.update_digests(
        conn,
        opening_id=opening_id,
        digester=deps.digester,
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
    deps: RunDispatchDeps,
) -> ResumeResult:
    """Resume one opening's research from its trace, spending `turns_requested` more
    turns (the caller caps this by `research_block_turns` and the remaining batch
    size — there is no separate per-opening lifetime cap). Returns the number of turns
    actually spent and the dispatch stop reason.
    """
    company = get_company(conn, opening.company_id)
    if company is None:  # pragma: no cover — FK constraint on openings.company_id
        raise NoSuchOpeningError(f"no company with id {opening.company_id!r}")
    research_trace_path = research_trace_path_for(data_root, opening.research_trace_id)
    page_content, url = read_page_content(research_trace_path)
    replay = replay_research_trace(research_trace_path)
    if turns_requested <= 0:
        return ResumeResult(turns_spent=0, stopped_reason="no remaining budget")

    assertions = assertions_for_opening(conn, opening.id)
    dispatch_deps = dataclasses.replace(
        deps, on_event=lambda event: record_event(research_trace_path, event)
    )
    stopped_reason = run_dispatch(
        conn,
        opening.id,
        url,
        assertions,
        company_id=company.id,
        page_content=page_content,
        company_name=company.name,
        opening_title=opening.title,
        turn_budget=replay.turns_used + turns_requested,
        resume=replay,
        deps=dispatch_deps,
    )
    turns_used_after = replay_research_trace(research_trace_path).turns_used
    return ResumeResult(
        turns_spent=turns_used_after - replay.turns_used, stopped_reason=stopped_reason
    )


def opening_weight(conn: sqlite3.Connection, opening: Opening, config: ScoringConfig) -> float:
    """Aggregate remaining uncertainty for one opening, assembled the same way
    `get_queue` assembles rulings for scoring — the latest ruling per
    assertion id."""
    assertions = assertions_for_opening(conn, opening.id)
    rulings: dict[str, Fit] = {
        ruling.assertion_id: ruling.fit
        for ruling in assertion_rulings_for_opening(conn, opening.id)
    }
    return aggregate_uncertainty(assertions, config, rulings)


def eligible_weights(conn: sqlite3.Connection, config: ScoringConfig) -> dict[str, float]:
    """Every opening still in the `screening` stage, mapped to a draw weight biased
    toward the current top-K boundary: uncertainty times `bandit.boundary_weight` of
    the opening's `p_top_k` from a fresh pool-wide rank (scouting research-targeting
    F16, F21 — breadth-first, biased toward fresh/contested openings over settling
    already-examined ones). There is no separate per-opening turn budget to filter on —
    the weight itself throttles: a fully examined opening's uncertainty decays toward 0,
    and an opening that looks settled out of top K decays toward `boundary_weight_floor`,
    which keeps it drawable. Recomputed fresh on every call — the caller redraws from
    this after each turn so a just-spent turn's new assertions immediately affect the
    next draw."""
    eligible = list_openings(conn, stage="screening")
    if not eligible:
        return {}
    uncertainty = {opening.id: opening_weight(conn, opening, config) for opening in eligible}
    ranks = rank_screening_pool(conn, config)
    p_top_k = {r.opening_id: r.p_top_k for r in ranks.opening_ranks_unguarded}
    return {
        opening_id: unc * boundary_weight(p_top_k[opening_id], config.boundary_weight_floor)
        for opening_id, unc in uncertainty.items()
    }


@dataclass
class DrawEvent:
    """Summary of one bandit draw (one opportunity to work a line of inquiry
    on an opening). Reported for tracing: which opening was drawn, how its rank
    and assertion count changed across the whole block, and why it stopped."""

    opening_id: str
    draw_probability: float
    rank_before: int
    rank_after: int
    assertions_before: int
    assertions_after: int
    turns_spent: int
    stopped_reason: str


def print_draw_event(event: DrawEvent) -> None:
    """Console trace for one bandit opportunity, summarized per opportunity rather
    than per action."""
    print(
        f"drew {event.opening_id} (p={event.draw_probability:.3f}, "
        f"rank {event.rank_before}->{event.rank_after}, "
        f"assertions {event.assertions_before}->{event.assertions_after}, "
        f"spent {event.turns_spent} turns, stopped: {event.stopped_reason})"
    )


@dataclass
class BatchProgress:
    """Mutable progress state shared between the background worker and the
    polling web route. Single-uvicorn-worker assumption; not persisted. `rate` is
    seconds per turn."""

    total: int = 0
    spent: int = 0
    current_opening_id: str | None = None
    touched: list[str] = field(default_factory=list)
    running: bool = False
    started_at: float | None = None
    rate: float | None = None
    eta_seconds: float | None = None


def _draw_event(
    opening_id: str,
    weights_before: dict[str, float],
    weights_after: dict[str, float],
    *,
    assertions_before: int,
    assertions_after: int,
    result: ResumeResult,
) -> DrawEvent:
    draw_weight = weights_before[opening_id]
    draw_probability = draw_weight / sum(weights_before.values())
    rank_before = sorted(weights_before.values(), reverse=True).index(draw_weight) + 1
    after_weight = weights_after.get(opening_id, 0.0)
    ranked_after = sorted(weights_after.values(), reverse=True)
    rank_after = (
        ranked_after.index(after_weight) + 1 if opening_id in weights_after else len(weights_before)
    )
    return DrawEvent(
        opening_id=opening_id,
        draw_probability=draw_probability,
        rank_before=rank_before,
        rank_after=rank_after,
        assertions_before=assertions_before,
        assertions_after=assertions_after,
        turns_spent=result.turns_spent,
        stopped_reason=result.stopped_reason,
    )


def _run_batch_turn(
    conn: sqlite3.Connection,
    data_root: Path,
    cfg: ScoringConfig,
    weights: dict[str, float],
    rng: np.random.Generator,
    *,
    batch_size: int,
    total_spent: int,
    touched: list[str],
    progress: BatchProgress,
    planner_factory: Callable[[], PlannerProtocol] | None,
    deps: RunDispatchDeps,
) -> tuple[str, int, DrawEvent | None]:
    """Draw one opening and spend up to one block of actions on it before the next
    draw. The block size is capped by `research_block_turns` and the remaining
    batch budget. Returns `(opening_id, actions_spent, draw_event)`; `draw_event` is
    `None` when the planner stalled without spending any actions, so the caller can
    stop redrawing it this batch.
    """
    opening_id = draw_opening(weights, rng)
    opening = cast(Opening, get_opening(conn, opening_id))
    progress.current_opening_id = opening_id
    turn_deps = (
        dataclasses.replace(deps, planner=planner_factory())
        if planner_factory is not None
        else deps
    )
    block_size = min(cfg.research_block_turns, batch_size - total_spent)
    if block_size <= 0:
        return opening_id, 0, None
    assertions_before = len(assertions_for_opening(conn, opening_id))
    result = resume_opening(
        conn,
        data_root,
        opening,
        block_size,
        deps=turn_deps,
    )
    if result.turns_spent == 0:
        return opening_id, 0, None
    if opening_id not in touched:
        touched.append(opening_id)
    weights_after = eligible_weights(conn, cfg)
    assertions_after = len(assertions_for_opening(conn, opening_id))
    return (
        opening_id,
        result.turns_spent,
        _draw_event(
            opening_id,
            weights,
            weights_after,
            assertions_before=assertions_before,
            assertions_after=assertions_after,
            result=result,
        ),
    )


def _begin_progress(progress: BatchProgress, batch_size: int, now_fn: Callable[[], float]) -> None:
    progress.total = batch_size
    progress.running = True
    progress.started_at = now_fn()
    progress.rate = None
    progress.eta_seconds = None


def _end_progress(progress: BatchProgress, total_spent: int, touched: list[str]) -> None:
    progress.spent = total_spent
    progress.touched = touched
    progress.running = False
    progress.current_opening_id = None
    progress.eta_seconds = None


_ETA_SMOOTHING = 0.3  # tqdm's default smoothing factor for its speed EMA


def _update_eta(
    progress: BatchProgress,
    *,
    turns_spent_this_call: int,
    total_spent: int,
    batch_size: int,
    elapsed: float,
    now_fn: Callable[[], float],
) -> None:
    """Update the seconds-per-turn EMA and the remaining-time estimate it implies.
    Mirrors tqdm's own rate smoothing (search, tqdm docs): a fresh sample only ever
    nudges the average, so one slow turn doesn't swing the ETA."""
    if elapsed <= 0:
        return
    sample_rate = elapsed / turns_spent_this_call
    prior_rate = progress.rate
    rate = (
        sample_rate
        if prior_rate is None
        else _ETA_SMOOTHING * sample_rate + (1 - _ETA_SMOOTHING) * prior_rate
    )
    progress.rate = rate
    progress.eta_seconds = max(batch_size - total_spent, 0) * rate


def run_batch(
    conn: sqlite3.Connection,
    data_root: Path,
    batch_size: int,
    progress: BatchProgress | None = None,
    *,
    deps: RunDispatchDeps,
    config: ScoringConfig | None = None,
    planner_factory: Callable[[], PlannerProtocol] | None = None,
    on_draw: Callable[[DrawEvent], None] | None = None,
    now_fn: Callable[[], float] = time.perf_counter,
) -> tuple[int, list[str]]:
    """Spend up to `batch_size` actions on opportunities drawn by aggregate remaining
    uncertainty. Each opportunity is a block of up to `research_block_turns`
    actions on one opening, capped by the remaining batch budget, so the planner can work down a line of inquiry before the next draw.
    The draw is seeded from `config.seed`, so a batch run against an unchanged DB snapshot
    reproduces the same sequence of draws.

    Returns (total_actions_spent, touched_opening_ids). `progress` is updated in place
    so a polling web route can observe `spent`, `current_opening_id`, `touched`, and
    `eta_seconds` while the batch runs. `on_draw`, if given, is called once per
    opportunity with a `DrawEvent` summarizing what changed about that opening during
    the block. `now_fn` is a monotonic clock, injectable so tests can control elapsed
    time without sleeping.

    `deps` carries browser/extractor/digester, held for the whole batch run.
    `planner_factory`, if given, is called once per opportunity — the planner is
    stateful across the actions in a block in the test fakes, so it can't be reused
    across draws the way the other collaborators are; omitted, `deps.planner` is
    reused for every draw instead.
    """
    cfg = config if config is not None else load_scoring_config()
    progress = progress if progress is not None else BatchProgress()
    rng = np.random.default_rng(cfg.seed)
    touched: list[str] = []
    stalled: set[str] = set()
    total_spent = 0
    _begin_progress(progress, batch_size, now_fn)
    while total_spent < batch_size:
        weights = {
            opening_id: weight
            for opening_id, weight in eligible_weights(conn, cfg).items()
            if opening_id not in stalled
        }
        if not weights:
            break
        turn_started = now_fn()
        opening_id, spent, draw_event = _run_batch_turn(
            conn,
            data_root,
            cfg,
            weights,
            rng,
            batch_size=batch_size,
            total_spent=total_spent,
            touched=touched,
            progress=progress,
            planner_factory=planner_factory,
            deps=deps,
        )
        if spent == 0:
            stalled.add(opening_id)
            continue
        assert draw_event is not None  # spent > 0 always pairs with a draw_event
        total_spent += spent
        _update_eta(
            progress,
            turns_spent_this_call=spent,
            total_spent=total_spent,
            batch_size=batch_size,
            elapsed=now_fn() - turn_started,
            now_fn=now_fn,
        )
        progress.spent = total_spent
        progress.touched = touched
        if on_draw is not None:
            on_draw(draw_event)
    _end_progress(progress, total_spent, touched)
    return total_spent, touched


_SECONDS_PER_MINUTE = 60


def eta_text(seconds: float) -> str:
    """Round an ETA down to a coarse human phrase: seconds under a minute, otherwise
    whole minutes. The estimate is noisy (a per-turn EMA); false precision would claim
    more than the number knows."""
    seconds = max(seconds, 0.0)
    if seconds < _SECONDS_PER_MINUTE:
        return f"{round(seconds)}s"
    return f"{round(seconds / _SECONDS_PER_MINUTE)}m"


@dataclass
class BatchEngine:
    """Runs a research batch off the request thread. `planner_factory` supplies a fresh
    planner per draw; `deps_factory` the batch's other collaborators."""

    planner_factory: Callable[[], PlannerProtocol]
    deps_factory: Callable[[], RunDispatchDeps]

    def run(
        self,
        db_path: Path,
        batch_size: int,
        progress: BatchProgress,
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
                deps=self.deps_factory(),
                on_draw=print_draw_event,
            )
        finally:
            conn.close()
