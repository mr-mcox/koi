"""The comparison surface: the picker's next pair, the operator's ruling on it, the
pre-screen polling page, and the review of Jev's provisional rulings. Whether a cached
suggestion may be served is decided in `screen.compare.session`; this module only
renders and schedules."""

import hashlib
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Annotated, cast
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from screen.api.deps import app_deps, app_state
from screen.compare.picker import ComparisonSuggestion
from screen.compare.prescreen import (
    CompareProgress,
    comparison_key,
    run_prescreen_in_background,
    run_speculative_prescreen_in_background,
)
from screen.compare.probability import pre_comparison_probability
from screen.compare.session import (
    cache_rejection,
    claim_speculation,
    needs_prescreen,
    record_operator_write,
)
from screen.digest.protocol import DigesterProtocol
from screen.pool import latest_ruling_by_assertion
from screen.score.loader import load_scoring_config
from screen.score.scorer import stats_for_target
from screen.score.types import FIT_VALUES, ScoringConfig
from screen.store.repo import (
    active_provisional_comparisons,
    append_comparison,
    assertion_rulings_for_opening,
    assertions_for_opening,
    get_opening,
)
from screen.types import (
    AssertionRuling,
    Comparison,
    ComparisonOutcome,
    Fit,
    Opening,
    Target,
)
from screen.web.common import Conn, DimensionGroup, company_for, dimension_groups, templates

# Throughput instrumentation for the compare loop: every cache decision and pre-screen
# transition is logged so a live session can be read back for where the operator waited.
_compare_log = logging.getLogger("screen.compare")

router = APIRouter()


def _should_swap_display_order(opening_a_id: str, opening_b_id: str, target: str) -> bool:
    """Whether the comparison preview should show B on the left. Deterministic (a hash
    of the pair + target, not a stateless coin flip) so re-rendering the same comparison
    — e.g. after editing a ruling — doesn't shuffle sides mid-review, while which pair
    lands on which side is still unpredictable to the operator across different
    comparisons (so left isn't always A)."""
    digest = hashlib.sha256(f"{opening_a_id}|{opening_b_id}|{target}".encode()).digest()
    return digest[0] % 2 == 1


def _compare_target_context(
    conn: sqlite3.Connection,
    opening_a: Opening,
    opening_b: Opening,
    target: str,
    config: ScoringConfig,
    *,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
    redirect_url: str,
) -> dict[str, object]:
    """Digest and assertion-derived prior for one target across two openings — the
    comparison surface reuses the same `dimension_groups` the rating view uses, but
    only keeps the group for the selected target. Display order (left/right) is a
    deterministic function of the pair and target, not always A-on-the-left, so the
    operator can't infer which opening is "A" from position alone; it stays stable
    across reloads of the same pair (e.g. after editing a ruling) since it isn't a
    fresh coin flip each render."""
    opening_a_id, opening_b_id = opening_a.id, opening_b.id
    swapped = _should_swap_display_order(opening_a_id, opening_b_id, target)
    opening_left, opening_right = (opening_b, opening_a) if swapped else (opening_a, opening_b)

    def _group(opening_id: str) -> DimensionGroup | None:
        groups = dimension_groups(
            conn,
            opening_id,
            assertions_for_opening(conn, opening_id),
            config,
            digester=digester,
            rubric_text=rubric_text,
            now=now,
        )
        return next((g for g in groups if g.target == target), None)

    def _rulings(opening_id: str) -> dict[str, AssertionRuling]:
        return latest_ruling_by_assertion(assertion_rulings_for_opening(conn, opening_id))

    def _fits(opening_id: str) -> dict[str, Fit]:
        return {assertion_id: ruling.fit for assertion_id, ruling in _rulings(opening_id).items()}

    stats_a = stats_for_target(
        assertions_for_opening(conn, opening_a_id),
        config,
        target,
        _fits(opening_a_id) or None,
    )
    stats_b = stats_for_target(
        assertions_for_opening(conn, opening_b_id),
        config,
        target,
        _fits(opening_b_id) or None,
    )
    group_a = _group(opening_a_id)
    group_b = _group(opening_b_id)
    return {
        "target": target,
        "opening_left": opening_left,
        "opening_right": opening_right,
        "group_left": group_b if swapped else group_a,
        "group_right": group_a if swapped else group_b,
        "rulings_left": _rulings(opening_left.id),
        "rulings_right": _rulings(opening_right.id),
        "outcome_left": "b" if swapped else "a",
        "outcome_right": "a" if swapped else "b",
        "fit_values": list(FIT_VALUES),
        "redirect_url": redirect_url,
        "opening_a_digest_version": group_a.digest_version if group_a else None,
        "opening_b_digest_version": group_b.digest_version if group_b else None,
        "predicted_a_beats_b": pre_comparison_probability(
            stats_a.mean, stats_a.half_width, stats_b.mean, stats_b.half_width
        ),
    }


def _start_compare_prescreen(
    request: Request, config: ScoringConfig, background_tasks: BackgroundTasks
) -> CompareProgress:
    session = app_state(request).compare
    session.progress = CompareProgress(running=True, version=session.state.version)
    _compare_log.info("prescreen scheduled (compare_version=%s)", session.state.version)
    background_tasks.add_task(
        run_prescreen_in_background,
        request.app.state.database.db_path,
        config,
        verdict_provider=app_deps(request).verdict_provider,
        rubric=app_deps(request).rubric,
        compare_state=session.state,
        compare_cache=session.cache,
        progress=session.progress,
    )
    return session.progress


def _start_speculation(
    request: Request,
    config: ScoringConfig,
    background_tasks: BackgroundTasks,
    on_screen: ComparisonSuggestion,
) -> None:
    """Use the operator's thinking time: while they decide the comparison being rendered,
    work out what comes after it."""
    session = app_state(request).compare
    if not claim_speculation(session, on_screen):
        return
    _compare_log.info("speculation scheduled for what follows %s", on_screen.target)
    background_tasks.add_task(
        run_speculative_prescreen_in_background,
        request.app.state.database.db_path,
        config,
        verdict_provider=app_deps(request).verdict_provider,
        rubric=app_deps(request).rubric,
        compare_state=session.state,
        compare_cache=session.cache,
    )


def _resume_or_start_prescreen(
    request: Request,
    conn: sqlite3.Connection,
    config: ScoringConfig,
    background_tasks: BackgroundTasks,
) -> tuple[str | None, str | None, str | None, HTMLResponse | None]:
    """Triggers (or polls) the background pre-screen pass. Returns the picker's resolved
    pair/dimension, or — while the pass is still running — an early `HTMLResponse` (the
    polling page) the caller should return as-is."""
    session = app_state(request).compare
    compare_state, compare_cache = session.state, session.cache
    rejection = cache_rejection(conn, config, session)
    if rejection is None:
        suggestion = compare_cache.suggestion
        assert suggestion is not None
        _compare_log.info(
            "compare cache hit (%s, cache_version=%s, compare_version=%s)",
            "exact" if compare_cache.version == compare_state.version else "stale-by-one",
            compare_cache.version,
            compare_state.version,
        )
        if needs_prescreen(session):
            _start_compare_prescreen(request, config, background_tasks)
        else:
            _start_speculation(request, config, background_tasks, suggestion)
        return (
            suggestion.opening_a_id,
            suggestion.opening_b_id,
            suggestion.target,
            None,
        )
    _compare_log.info(
        "compare cache miss: %s (cache_version=%s, compare_version=%s)",
        rejection,
        compare_cache.version,
        compare_state.version,
    )
    progress = session.progress
    if needs_prescreen(session):
        progress = _start_compare_prescreen(request, config, background_tasks)
    if progress.running:
        _compare_log.info(
            "compare waiting on prescreen (compare_version=%s)", compare_state.version
        )
        early = templates.TemplateResponse(
            request, "compare_prescreening.html", {"progress": progress}
        )
        return None, None, None, early
    _compare_log.debug("compare has nothing to suggest (compare_version=%s)", compare_state.version)
    return None, None, None, None


@router.get("/compare", response_class=HTMLResponse)
def compare(
    request: Request,
    conn: Conn,
    background_tasks: BackgroundTasks,
    opening_a_id: str | None = None,
    opening_b_id: str | None = None,
    target: str | None = None,
) -> HTMLResponse:
    """Comparison surface: the backend picker chooses the pair/dimension by default, the
    operator judges it, and the screen immediately hands over the next one — there is no
    operator-facing selection UI. The three query parameters are not linked from anywhere
    in the UI; they exist only so a specific pair can be reached directly (fixtures,
    debugging, a bookmarked link), and when given they still render through the same
    preview/redirect path the picker uses.

    Given no parameters, a pre-screen pass runs first: Jev rules every confidently-gated
    pair before the operator sees anything, so attention never lands on a pair the
    pipeline already settled. The pass runs in the background and this route renders a
    polling status page while it's in flight (`_compare_status.html`, same pattern as
    `/batch`/`/batch-status`); once it finishes, the normal picker suggestion renders."""
    config = load_scoring_config()
    if not (opening_a_id and opening_b_id and target):
        opening_a_id, opening_b_id, target, early = _resume_or_start_prescreen(
            request, conn, config, background_tasks
        )
        if early is not None:
            return early
    context: dict[str, object] = {
        "opening_a_id": opening_a_id,
        "opening_b_id": opening_b_id,
        "target": target,
    }
    if opening_a_id and opening_b_id and target and target in config.dimension_weights:
        opening_a = get_opening(conn, opening_a_id)
        opening_b = get_opening(conn, opening_b_id)
        if opening_a is None or opening_b is None or opening_a_id == opening_b_id:
            raise HTTPException(status_code=400, detail="invalid opening pair")
        redirect_url = "/compare?" + urlencode(
            {"opening_a_id": opening_a_id, "opening_b_id": opening_b_id, "target": target}
        )
        context.update(
            _compare_target_context(
                conn,
                opening_a,
                opening_b,
                target,
                config,
                digester=app_deps(request).digester,
                rubric_text=app_deps(request).rubric.full(),
                now=datetime.now(UTC),
                redirect_url=redirect_url,
            )
        )
    return templates.TemplateResponse(request, "compare.html", context)


@router.post("/compare")
def submit_comparison(
    request: Request,
    background_tasks: BackgroundTasks,
    conn: Conn,
    opening_a_id: Annotated[str, Form()],
    opening_b_id: Annotated[str, Form()],
    target: Annotated[str, Form()],
    outcome: Annotated[str, Form()],
    opening_a_digest_version: Annotated[str, Form()] = "",
    opening_b_digest_version: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Record one operator comparison between two openings on a single scoring
    dimension, then redirect straight to the next comparison the picker hands over —
    the operator judges continuously without returning to the queue between pairs."""
    config = load_scoring_config()
    if target not in config.dimension_weights:
        raise HTTPException(status_code=400, detail=f"invalid target: {target}")
    opening_a = get_opening(conn, opening_a_id)
    opening_b = get_opening(conn, opening_b_id)
    if opening_a is None or opening_b is None:
        raise HTTPException(status_code=404, detail="opening not found")
    if opening_a_id == opening_b_id:
        raise HTTPException(status_code=400, detail="must compare two different openings")
    if outcome not in {"a", "b", "tie"}:
        raise HTTPException(status_code=400, detail=f"invalid outcome: {outcome}")

    def _rulings(opening_id: str) -> dict[str, Fit]:
        return {
            ruling.assertion_id: ruling.fit
            for ruling in latest_ruling_by_assertion(
                assertion_rulings_for_opening(conn, opening_id)
            ).values()
        }

    stats_a = stats_for_target(
        assertions_for_opening(conn, opening_a_id),
        config,
        target,
        _rulings(opening_a_id) or None,
    )
    stats_b = stats_for_target(
        assertions_for_opening(conn, opening_b_id),
        config,
        target,
        _rulings(opening_b_id) or None,
    )
    predicted_a_beats_b = pre_comparison_probability(
        stats_a.mean, stats_a.half_width, stats_b.mean, stats_b.half_width
    )
    append_comparison(
        conn,
        Comparison(
            id=str(uuid4()),
            opening_a_id=opening_a_id,
            opening_b_id=opening_b_id,
            target=cast("Target", target),
            outcome=cast("ComparisonOutcome", outcome),
            predicted_a_beats_b=predicted_a_beats_b,
            opening_a_digest_version=opening_a_digest_version or None,
            opening_b_digest_version=opening_b_digest_version or None,
            created_at=datetime.now(UTC),
        ),
    )
    session = app_state(request).compare
    record_operator_write(session, comparison_key(opening_a_id, opening_b_id, target))
    if not session.progress.running:
        _start_compare_prescreen(request, config, background_tasks)
    return RedirectResponse("/compare", status_code=303)


@router.get("/compare-status", response_class=HTMLResponse)
def compare_status(request: Request) -> HTMLResponse:
    """Polling endpoint for the running (or just-finished) comparison pre-screen pass.
    Rendered as a small partial `/compare` swaps in via HTMX; once the pass finishes, it
    tells the browser to reload `/compare` (`HX-Redirect`) so the normal picker-suggestion
    flow takes over — the status partial itself never renders a comparison."""
    progress = app_state(request).compare.progress
    response = templates.TemplateResponse(request, "_compare_status.html", {"progress": progress})
    if not progress.running:
        response.headers["HX-Redirect"] = "/compare"
    return response


@router.get("/compare/review", response_class=HTMLResponse)
def compare_review(request: Request, conn: Conn) -> HTMLResponse:
    """Every provisional comparison Jev has ruled and the operator hasn't overridden,
    newest first. Overriding is the normal compare form for that exact pair/target — a
    later operator-provenance row on the same (pair, target) displaces the provisional
    one (the existing dedup-to-latest reduction), so there is no separate override
    mechanism to maintain here."""
    provisional = sorted(
        active_provisional_comparisons(conn), key=lambda c: c.created_at, reverse=True
    )
    companies_by_opening_id: dict[str, str] = {}
    titles_by_opening_id: dict[str, str] = {}
    for comparison in provisional:
        for opening_id in (comparison.opening_a_id, comparison.opening_b_id):
            if opening_id in companies_by_opening_id:
                continue
            # `comparisons` references `openings` with foreign keys on.
            opening = cast(Opening, get_opening(conn, opening_id))
            titles_by_opening_id[opening_id] = opening.title
            companies_by_opening_id[opening_id] = company_for(conn, opening).name
    return templates.TemplateResponse(
        request,
        "compare_review.html",
        {
            "comparisons": provisional,
            "companies_by_opening_id": companies_by_opening_id,
            "titles_by_opening_id": titles_by_opening_id,
        },
    )
