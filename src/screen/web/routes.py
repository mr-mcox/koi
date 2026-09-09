"""Server-rendered HTML routes for the review surface.

The queue and a per-opening rating view both call the same domain functions
(`score_opening`, `list_openings`, etc.) as the JSON routes in `screen.api.routes`.
The rating view also accepts assertion-ruling and dimension-ruling submissions via
HTMX partial swap (assertion-ruling-submit, dimension-ruling bearings) — the JSON
routes stay read-only and untouched.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from screen.api.deps import get_db
from screen.api.scoring import (
    OpeningScore,
    dimension_rulings_by_target,
    latest_ruling_by_assertion,
    score_opening,
)
from screen.digest.protocol import DigesterProtocol
from screen.digest.render import render_digest_html
from screen.digest.service import digest_for_target
from screen.extract.prompt import rubric_text_for_baml
from screen.research.batch import opening_research_status
from screen.score.boundary import crossing_probability
from screen.score.loader import load_scoring_config
from screen.score.triage import rating_task_candidates
from screen.score.types import FIT_VALUES, ScoringConfig
from screen.store.repo import (
    assertion_rulings_for_opening,
    assertions_for_opening,
    dimension_rulings_for_opening,
    get_company,
    get_opening,
    list_openings,
    upsert_assertion_ruling,
    upsert_dimension_ruling,
    upsert_opening,
)
from screen.types import (
    Assertion,
    AssertionRuling,
    Company,
    DimensionRuling,
    Fit,
    Opening,
    Stage,
    Target,
)

Conn = Annotated[sqlite3.Connection, Depends(get_db)]

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["render_digest_html"] = render_digest_html


@dataclass(frozen=True)
class _DimensionGroup:
    target: str
    digest: str
    assertions: list[Assertion]
    ruling: DimensionRuling | None
    show_dimension_context: bool = True
    """False only in the focused view, for a target whose budgeted task is an assertion
    ruling but not its own dimension-ruling task (review-ux/rating-voi-triage bearing,
    operator feedback): the digest and dimension-ruling pad belong to the bigger,
    unselected task and would be noise for a pure assertion-rating task."""

    @property
    def is_stale(self) -> bool:
        """A pin is stale once an assertion exists under its target that its snapshot
        didn't cover (dimension-ruling-drift bearing) — the pin's contribution to scoring
        no longer accounts for everything filed, though it's still in effect until the
        operator re-rules."""
        if self.ruling is None:
            return False
        covered = set(self.ruling.covered_assertion_ids)
        return any(a.id not in covered for a in self.assertions)


@dataclass(frozen=True)
class BoundaryGlyph:
    """Credible-interval bar on a fixed 0-1 `overall`-quality axis: `median` is the dot,
    `low`/`high` its q10/q90 bar (rendered as the bar's own edges, not separate end
    markers), and `boundary` (optional) the K-th opening's `median` — all on this one
    axis, never `standing`'s `P(> bar)` axis, whose single scalar has no per-draw
    quantile for the trace to bracket.
    `boundary`/`crossing_probability` are both `None` when the queue has fewer than
    `top_k` scored openings — no K-th opening means no boundary to show.
    """

    low: float
    median: float
    high: float
    boundary: float | None
    crossing_probability: float | None

    @property
    def low_pct(self) -> float:
        return self.low

    @property
    def median_pct(self) -> float:
        return self.median

    @property
    def high_pct(self) -> float:
        return self.high

    @property
    def boundary_pct(self) -> float | None:
        return self.boundary


def _boundary_glyph_for_score(
    score: OpeningScore,
    *,
    boundary: float | None,
    crossing_probability: float | None,
) -> BoundaryGlyph:
    """The glyph for one opening, given the queue's shared K-th-opening boundary (or
    `None` when fewer than `top_k` openings exist)."""
    return BoundaryGlyph(
        low=score.low,
        median=score.median,
        high=score.high,
        boundary=boundary,
        crossing_probability=crossing_probability,
    )


def _company_for(conn: sqlite3.Connection, opening: Opening) -> Company:
    """`Opening.company_id` is a foreign key with `PRAGMA foreign_keys = ON`
    (store/db.py) — the referenced company always exists."""
    return cast(Company, get_company(conn, opening.company_id))


def _hue_from_seed(seed: str, *, center: float, spread: float) -> float:
    """Deterministic decorative OKLCH hue (degrees) from a stable id. Styling only —
    never read by the scorer or stored; re-derived on every render."""
    digest = hashlib.sha256(seed.encode()).digest()
    frac = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return round(center + (frac - 0.5) * 2 * spread, 1)


def _accent_hues(company_id: str, opening_id: str) -> tuple[float, float]:
    """Company and opening accent hues, both within the koi-orange band (centered
    ~42°). The opening's hue is a small perturbation of its own company's — not an
    independent draw — so a company's openings read as kin, each opening still its
    own shade."""
    company_hue = _hue_from_seed(company_id, center=42, spread=16)
    opening_hue = _hue_from_seed(opening_id, center=company_hue, spread=6)
    return company_hue, opening_hue


def _dimension_groups(
    conn: sqlite3.Connection,
    opening_id: str,
    assertions: list[Assertion],
    config: ScoringConfig,
    *,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
    dimension_rulings: dict[str, DimensionRuling],
) -> list[_DimensionGroup]:
    """Group assertions by rubric target and attach the cached digest for each group.

    Dimensions are ordered by their declared weight descending (ties broken by slug);
    constraints follow in their rubric.yaml declared order. Any non-scoring targets with
    assertions are appended after. Empty scoring targets still render with a
    'not yet examined' digest so the operator can see coverage gaps at a glance.
    """
    dimension_order = sorted(
        config.dimension_weights,
        key=lambda slug: (-config.dimension_weights[slug], slug),
    )
    constraint_order = list(config.constraints)
    declared = dimension_order + constraint_order

    by_target: dict[str, list[Assertion]] = defaultdict(list)
    for a in assertions:
        by_target[a.target].append(a)

    all_targets = list(dict.fromkeys(declared + [a.target for a in assertions]))

    groups = []
    for target in all_targets:
        target_assertions = by_target.get(target, [])
        if target_assertions:
            digest = digest_for_target(
                conn,
                opening_id=opening_id,
                target=target,
                digester=digester,
                rubric_text=rubric_text,
                now=now,
            )
        else:
            digest = "not yet examined"
        groups.append(
            _DimensionGroup(
                target=target,
                digest=digest,
                assertions=target_assertions,
                ruling=dimension_rulings.get(target),
            )
        )
    return groups


def _scored_openings(
    conn: sqlite3.Connection, config: ScoringConfig
) -> list[tuple[Opening, Company, OpeningScore]]:
    """All openings scored with the same rulings the rating view uses, sorted by
    standing descending. Shared by the queue template and the contested review session
    so both see the same boundary."""
    scored: list[tuple[Opening, Company, OpeningScore]] = []
    for opening in list_openings(conn, stage="screening"):
        company = _company_for(conn, opening)
        assertions = assertions_for_opening(conn, opening.id)
        assertion_rulings = latest_ruling_by_assertion(
            assertion_rulings_for_opening(conn, opening.id)
        )
        dimension_rulings = dimension_rulings_by_target(
            dimension_rulings_for_opening(conn, opening.id)
        )
        ruled_fits: dict[str, Fit] = {
            assertion_id: ruling.fit for assertion_id, ruling in assertion_rulings.items()
        }
        result = score_opening(
            assertions,
            config,
            rulings=ruled_fits,
            dimension_rulings=dimension_rulings,
        )
        scored.append((opening, company, result))
    scored.sort(key=lambda row: row[2].standing, reverse=True)
    return scored


def _kth_result(
    scored: list[tuple[Opening, Company, OpeningScore]], config: ScoringConfig
) -> OpeningScore | None:
    """The K-th-ranked opening's `OpeningScore`, or `None` when fewer than `top_k`
    openings exist — no K-th opening means no boundary (S5-adjacent display
    convention)."""
    return scored[config.top_k - 1][2] if len(scored) >= config.top_k else None


def _queue_items(conn: sqlite3.Connection, data_root: Path) -> list[dict[str, object]]:
    """Build the same ranked list the JSON `/queue` returns, shaped for the template."""
    config = load_scoring_config()
    scored = _scored_openings(conn, config)
    kth = _kth_result(scored, config)
    items = []
    for opening, company, result in scored:
        company_hue, opening_hue = _accent_hues(company.id, opening.id)
        turns_used, turns_budget = opening_research_status(data_root, opening)
        items.append(
            {
                "opening_id": opening.id,
                "company_name": company.name,
                "opening_title": opening.title,
                "company_hue": company_hue,
                "opening_hue": opening_hue,
                "turns_used": turns_used,
                "turns_budget": turns_budget,
                "glyph": _boundary_glyph_for_score(
                    result,
                    boundary=kth.median if kth is not None else None,
                    crossing_probability=(
                        crossing_probability(result.standing_result, kth.standing_result)
                        if kth is not None
                        else None
                    ),
                ),
                "standing": result.standing,
            }
        )
    return items


def _contested_queue_items(conn: sqlite3.Connection) -> list[str]:
    """Opening ids ordered by descending P(rank crosses K), limited to openings that still
    have rating work available. Empty when fewer than `top_k` openings: no K-th opening
    means no boundary, so no crossing probability to order by. Also empty when none of
    the contested openings have actionable rating tasks — their uncertainty is inherent
    in the opportunity, not something the operator can resolve by rating."""
    config = load_scoring_config()
    scored = _scored_openings(conn, config)
    if len(scored) < config.top_k:
        return []
    kth = scored[config.top_k - 1][2].standing_result
    ordered = [
        (opening.id, crossing_probability(result.standing_result, kth))
        for opening, _, result in scored
        if _opening_leverage(conn, opening, config) > 0
    ]
    ordered.sort(key=lambda pair: pair[1], reverse=True)
    return [opening_id for opening_id, _ in ordered]


def _opening_leverage(conn: sqlite3.Connection, opening: Opening, config: ScoringConfig) -> float:
    """Aggregate rating leverage for one opening: sum of top `rating_task_budget` task
    swings. Orders "next opening" within a per-opening focus session (`focus_opening`) —
    the only remaining consumer; the cross-opening entry point that used to rank the
    whole backlog by this same number is gone."""
    assertions = assertions_for_opening(conn, opening.id)
    rulings = latest_ruling_by_assertion(assertion_rulings_for_opening(conn, opening.id))
    ruled_fits: dict[str, Fit] = {
        assertion_id: ruling.fit for assertion_id, ruling in rulings.items()
    }
    dimension_rulings = dimension_rulings_by_target(dimension_rulings_for_opening(conn, opening.id))
    candidates = rating_task_candidates(
        assertions, config, rulings=ruled_fits, dimension_rulings=dimension_rulings
    )
    return sum(c.swing for c in candidates)


def _focus_queue_items(conn: sqlite3.Connection) -> list[str]:
    """Opening ids ordered by aggregate rating leverage descending. Openings with zero
    remaining rating work are excluded."""
    config = load_scoring_config()
    leverages = [
        (opening.id, _opening_leverage(conn, opening, config))
        for opening in list_openings(conn, stage="screening")
    ]
    leverages.sort(key=lambda pair: pair[1], reverse=True)
    return [opening_id for opening_id, leverage in leverages if leverage > 0]


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: Conn) -> HTMLResponse:
    """The queue view: ranked openings as HTML."""
    data_root = request.app.state.database.data_root
    items = _queue_items(conn, data_root)
    status = request.app.state.batch_status
    return templates.TemplateResponse(request, "queue.html", {"items": items, "status": status})


@router.get("/contested")
def contested_session(request: Request, conn: Conn) -> RedirectResponse:
    """Entry point for a contested-boundary review session: redirect to the opening the
    crossing-probability signal ranks first, or back to the queue if the boundary
    doesn't exist."""
    ordered = _contested_queue_items(conn)
    if not ordered:
        return RedirectResponse("/", status_code=302)
    return RedirectResponse(f"/openings/{ordered[0]}/contested", status_code=302)


@router.get("/openings/{opening_id}/contested", response_class=HTMLResponse)
def contested_opening(request: Request, opening_id: str, conn: Conn) -> HTMLResponse:
    """The focused rating surface for one opening, wrapped in a contested-boundary
    review session. Reuses the focused per-opening UI (filtered to high-leverage tasks)
    but chains openings by the new crossing-probability signal, not the raw-swing order
    used by `/focus`. The probability value itself is not rendered; only the order and
    a next link are exposed."""
    context = _focus_context_for_request(request, conn, opening_id)
    ordered = _contested_queue_items(conn)
    try:
        idx = ordered.index(opening_id)
    except ValueError:
        idx = None
    next_contested_id = ordered[idx + 1] if idx is not None and idx + 1 < len(ordered) else None
    return templates.TemplateResponse(
        request,
        "rating.html",
        {**context, "contested": True, "next_contested_id": next_contested_id},
    )


def _rating_context(
    conn: sqlite3.Connection,
    opening_id: str,
    *,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
) -> dict[str, object]:
    """Everything the rating page (and its HTMX partial) render — shared so a fresh
    GET and a post-ruling swap can never drift out of agreement (Approach: HTMX swaps
    the whole rating-content block, not hand-picked sub-fragments)."""
    opening = get_opening(conn, opening_id)
    if opening is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    company = _company_for(conn, opening)
    assertions = assertions_for_opening(conn, opening_id)
    rulings = latest_ruling_by_assertion(assertion_rulings_for_opening(conn, opening_id))
    ruled_fits: dict[str, Fit] = {
        assertion_id: ruling.fit for assertion_id, ruling in rulings.items()
    }
    dimension_rulings = dimension_rulings_by_target(dimension_rulings_for_opening(conn, opening_id))
    config = load_scoring_config()
    score = score_opening(
        assertions, config, rulings=ruled_fits, dimension_rulings=dimension_rulings
    )
    kth = _kth_result(_scored_openings(conn, config), config)
    company_hue, opening_hue = _accent_hues(company.id, opening_id)
    groups = _dimension_groups(
        conn,
        opening_id=opening_id,
        assertions=assertions,
        config=config,
        digester=digester,
        rubric_text=rubric_text,
        now=now,
        dimension_rulings=dimension_rulings,
    )
    return {
        "opening": opening,
        "company": company,
        "groups": groups,
        "score": score,
        "score_glyph": _boundary_glyph_for_score(
            score,
            boundary=kth.median if kth is not None else None,
            crossing_probability=(
                crossing_probability(score.standing_result, kth.standing_result)
                if kth is not None
                else None
            ),
        ),
        "rulings": rulings,
        "fit_values": list(FIT_VALUES),
        "focus": False,
        "candidate_assertion_ids": set(),
        "company_hue": company_hue,
        "opening_hue": opening_hue,
    }


def _focus_context(
    conn: sqlite3.Connection,
    opening_id: str,
    *,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
    snapshot_assertion_ids: set[str] | None = None,
    snapshot_dimension_targets: set[Target] | None = None,
) -> dict[str, object]:
    """The focused view's data: `_rating_context`'s full context, narrowed to the
    highest-leverage unrated tasks. Reuses `_rating_context`'s assembly rather than
    re-deriving it — only the `groups` list is filtered afterward.

    Without a snapshot (first GET of the focused view), the task set is freshly ranked.
    With one (an HTMX submit echoing back the initial GET's task identifiers), the task
    set is exactly that snapshot — not recomputed — so the operator's screen holds
    steady for the whole focus session: a just-completed task doesn't vanish, and no
    newly-eligible task appears mid-session (operator feedback; recomputing after every
    submission did both)."""
    use_snapshot = snapshot_assertion_ids is not None or snapshot_dimension_targets is not None

    context = _rating_context(
        conn,
        opening_id,
        digester=digester,
        rubric_text=rubric_text,
        now=now,
    )

    assertions = assertions_for_opening(conn, opening_id)
    rulings = latest_ruling_by_assertion(assertion_rulings_for_opening(conn, opening_id))
    ruled_fits: dict[str, Fit] = {
        assertion_id: ruling.fit for assertion_id, ruling in rulings.items()
    }
    dimension_rulings = dimension_rulings_by_target(dimension_rulings_for_opening(conn, opening_id))
    config = load_scoring_config()
    if use_snapshot:
        candidate_assertion_ids = snapshot_assertion_ids or set()
        candidate_dimension_targets = snapshot_dimension_targets or set()
        candidate_targets = set(candidate_dimension_targets)
        # Derive candidate targets for the assertion side of the snapshot.
        candidate_targets |= {a.target for a in assertions if a.id in candidate_assertion_ids}
        candidate_dimension_targets_csv = "|".join(sorted(candidate_dimension_targets))
        candidate_assertion_ids_csv = "|".join(sorted(candidate_assertion_ids))
    else:
        candidates = rating_task_candidates(
            assertions,
            config,
            rulings=ruled_fits,
            dimension_rulings=dimension_rulings,
        )
        candidate_assertion_ids = {c.assertion_id for c in candidates if c.assertion_id is not None}
        candidate_dimension_targets = {c.target for c in candidates if c.assertion_id is None}
        candidate_targets = {c.target for c in candidates}
        candidate_dimension_targets_csv = "|".join(sorted(candidate_dimension_targets))
        candidate_assertion_ids_csv = "|".join(sorted(candidate_assertion_ids))
    groups = cast(list[_DimensionGroup], context["groups"])
    focused_groups: list[_DimensionGroup] = []
    for group in groups:
        if group.target not in candidate_targets:
            continue

        show_dimension_context = group.target in candidate_dimension_targets
        group_has_assertion_candidates = any(
            a.id in candidate_assertion_ids for a in group.assertions
        )

        focused_group = _DimensionGroup(
            target=group.target,
            digest=group.digest,
            ruling=group.ruling,
            show_dimension_context=show_dimension_context,
            assertions=(
                group.assertions
                if show_dimension_context
                else (
                    [a for a in group.assertions if a.id in candidate_assertion_ids]
                    if group_has_assertion_candidates
                    else group.assertions
                )
            ),
        )
        focused_groups.append(focused_group)

    return {
        **context,
        "groups": focused_groups,
        "focus": True,
        "candidate_assertion_ids": candidate_assertion_ids,
        # These define the stable task set for the duration of the focus-screen
        # (until operator reloads/navigates away). They are echoed back on HTMX
        # submissions as hidden fields.
        "focus_snapshot_assertion_ids_csv": candidate_assertion_ids_csv,
        "focus_snapshot_dimension_targets_csv": candidate_dimension_targets_csv,
    }


def _rating_context_for_request(
    request: Request, conn: sqlite3.Connection, opening_id: str
) -> dict[str, object]:
    """Thin wrapper pulling the digester off `request.app.state` — shared by the GET
    and both ruling-submit routes so each doesn't repeat the same three keyword args."""
    return _rating_context(
        conn,
        opening_id,
        digester=request.app.state.digester,
        rubric_text=rubric_text_for_baml(),
        now=datetime.now(UTC),
    )


def _focus_context_for_request(
    request: Request,
    conn: sqlite3.Connection,
    opening_id: str,
    *,
    snapshot_assertion_ids: set[str] | None = None,
    snapshot_dimension_targets: set[Target] | None = None,
) -> dict[str, object]:
    """Thin wrapper mirroring `_rating_context_for_request`, for the focused view."""
    return _focus_context(
        conn,
        opening_id,
        digester=request.app.state.digester,
        rubric_text=rubric_text_for_baml(),
        now=datetime.now(UTC),
        snapshot_assertion_ids=snapshot_assertion_ids,
        snapshot_dimension_targets=snapshot_dimension_targets,
    )


@router.get("/openings/{opening_id}/rate", response_class=HTMLResponse)
def rate_opening(request: Request, opening_id: str, conn: Conn) -> HTMLResponse:
    """The rating surface for one opening: its score, dimension-grouped assertions
    (each with a cached digest), and any recorded rulings, with per-assertion
    override controls."""
    context = _rating_context_for_request(request, conn, opening_id)
    return templates.TemplateResponse(request, "rating.html", context)


@router.get("/openings/{opening_id}/focus", response_class=HTMLResponse)
def focus_opening(request: Request, opening_id: str, conn: Conn) -> HTMLResponse:
    """The focused rating surface for one opening: only the highest-leverage unrated
    tasks, rendered with the same template family as the full rating page."""
    context = _focus_context_for_request(request, conn, opening_id)
    ordered = _focus_queue_items(conn)
    try:
        idx = ordered.index(opening_id)
    except ValueError:
        idx = None
    next_opening_id = ordered[idx + 1] if idx is not None and idx + 1 < len(ordered) else None
    return templates.TemplateResponse(
        request, "rating.html", {**context, "next_opening_id": next_opening_id}
    )


def _parse_snapshot_csv(value: str) -> set[str]:
    """Parse the `|`-joined snapshot fields the focused view echoes back on each HTMX
    submit (`focus_snapshot_assertion_ids`/`focus_snapshot_dimension_targets`) — this is
    what keeps the focused screen's task set stable for its whole session (bearing,
    operator feedback): the initial GET's budgeted tasks, not a set recomputed after
    every submission, which would both drop just-completed tasks and admit new ones
    mid-session."""
    return {item for item in value.split("|") if item}


@router.post("/openings/{opening_id}/assertions/{assertion_id}/ruling", response_class=HTMLResponse)
def submit_ruling(
    *,
    request: Request,
    opening_id: str,
    assertion_id: str,
    conn: Conn,
    fit: Annotated[Fit, Form()],
    focus: bool = False,
    focus_snapshot_assertion_ids: Annotated[str, Form()] = "",
    focus_snapshot_dimension_targets: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Upsert the operator's ruling for one assertion, then return the rating-content
    partial (not a full document) for an HTMX swap. Submitting a rating must re-sort the
    queue without a full page reload, but that re-sort is the queue page's concern, not
    this fragment's. `focus=1` keeps the swap on the focused-view's narrowed context,
    not the full rating page's, so submitting from the focused view stays focused."""
    if get_opening(conn, opening_id) is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    upsert_assertion_ruling(
        conn,
        AssertionRuling(
            id=str(uuid4()), assertion_id=assertion_id, fit=fit, created_at=datetime.now(UTC)
        ),
    )
    context = (
        _focus_context_for_request(
            request,
            conn,
            opening_id,
            snapshot_assertion_ids=_parse_snapshot_csv(focus_snapshot_assertion_ids),
            snapshot_dimension_targets=cast(
                set[Target], _parse_snapshot_csv(focus_snapshot_dimension_targets)
            ),
        )
        if focus
        else _rating_context_for_request(request, conn, opening_id)
    )
    return templates.TemplateResponse(request, "_rating_content.html", context)


@router.post("/openings/{opening_id}/dimensions/{target}/ruling", response_class=HTMLResponse)
def submit_dimension_ruling(
    *,
    request: Request,
    opening_id: str,
    target: Target,
    conn: Conn,
    mean: Annotated[float, Form(ge=-1.0, le=1.0)],
    settledness: Annotated[float, Form(ge=0.0, le=1.0)],
    focus: bool = False,
    focus_snapshot_assertion_ids: Annotated[str, Form()] = "",
    focus_snapshot_dimension_targets: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Upsert the operator's dimension-level pin, then return the rating-content partial
    for an HTMX swap. Pins are not revertable — no unset route, no path back to
    unpinned, only resubmission via this same upsert. `focus=1` keeps the swap on the
    focused-view's narrowed context, matching `submit_ruling`."""
    if get_opening(conn, opening_id) is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    covered_assertion_ids = [
        a.id for a in assertions_for_opening(conn, opening_id) if a.target == target
    ]
    ruling = DimensionRuling(
        id=str(uuid4()),
        opening_id=opening_id,
        target=target,
        mean=mean,
        settledness=settledness,
        created_at=datetime.now(UTC),
        covered_assertion_ids=covered_assertion_ids,
    )
    upsert_dimension_ruling(conn, ruling)
    context = (
        _focus_context_for_request(
            request,
            conn,
            opening_id,
            snapshot_assertion_ids=_parse_snapshot_csv(focus_snapshot_assertion_ids),
            snapshot_dimension_targets=cast(
                set[Target], _parse_snapshot_csv(focus_snapshot_dimension_targets)
            ),
        )
        if focus
        else _rating_context_for_request(request, conn, opening_id)
    )
    return templates.TemplateResponse(request, "_rating_content.html", context)


STAGES: tuple[Stage, ...] = ("screening", "pursuing", "applied", "closed")


@router.post("/openings/{opening_id}/stage")
def submit_stage(
    opening_id: str,
    conn: Conn,
    stage: Annotated[Stage, Form()],
) -> RedirectResponse:
    """Move an opening to a new pipeline stage (opening-lifecycle bearing). A lightweight
    marker, not a full application tracker: no outcome sub-typing, no history kept of
    prior stages — the operator's existing Ruling/Assertion history already answers
    'what did I think of this' once the opening is reachable again via `/archive`.
    Redirects to the queue rather than swapping a partial: the opening usually just left
    the page the operator was looking at."""
    opening = get_opening(conn, opening_id)
    if opening is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    upsert_opening(conn, opening.model_copy(update={"stage": stage}))
    return RedirectResponse("/", status_code=303)


@router.get("/archive", response_class=HTMLResponse)
def archive(request: Request, conn: Conn, stage: Stage | None = None) -> HTMLResponse:
    """Every opening that has left the live queue, optionally filtered to one stage —
    the operator's retrieval path back to an opening's rulings and job description after
    it stops being ranked (F8/F15, opening-lifecycle bearing). Unranked: display order is
    stage then company, never standing."""
    stages_to_show = (stage,) if stage is not None else tuple(s for s in STAGES if s != "screening")
    items = []
    for show_stage in stages_to_show:
        for opening in list_openings(conn, stage=show_stage):
            company = _company_for(conn, opening)
            company_hue, opening_hue = _accent_hues(company.id, opening.id)
            items.append(
                {
                    "opening_id": opening.id,
                    "company_name": company.name,
                    "opening_title": opening.title,
                    "stage": opening.stage,
                    "company_hue": company_hue,
                    "opening_hue": opening_hue,
                }
            )
    return templates.TemplateResponse(
        request, "archive.html", {"items": items, "stages": STAGES, "selected_stage": stage}
    )


@router.post("/batch", response_class=HTMLResponse)
def start_batch(
    request: Request,
    conn: Conn,
    background_tasks: BackgroundTasks,
    batch_size: Annotated[int, Form(gt=0)],
) -> HTMLResponse:
    """Start a research batch and return immediately. The heavy work runs in a
    `BackgroundTasks` callback with its own DB connection, so the HTTP response
    lands before the first turn is spent.

    A second request while a batch is running is rejected with a clear message
    rather than queued or double-run.
    """
    status = request.app.state.batch_status
    if status.get("running"):
        return templates.TemplateResponse(
            request,
            "_batch_status.html",
            {
                "status": status,
                "error": "A batch is already running.",
            },
        )
    new_status: dict[str, object] = {
        "running": True,
        "total": batch_size,
        "spent": 0,
        "current_opening_id": None,
        "touched": [],
    }
    request.app.state.batch_status = new_status
    engine = request.app.state.batch_engine
    background_tasks.add_task(
        engine.run, request.app.state.database.db_path, batch_size, new_status
    )
    return templates.TemplateResponse(request, "_batch_status.html", {"status": new_status})


@router.get("/batch-status", response_class=HTMLResponse)
def batch_status(request: Request) -> HTMLResponse:
    """Polling endpoint for the currently running (or last completed) batch.
    Rendered as a small partial the queue page swaps in via HTMX."""
    status = request.app.state.batch_status
    return templates.TemplateResponse(request, "_batch_status.html", {"status": status})


# Static files: CSS, later HTMX assets, etc.
static_dir = Path(__file__).parent / "static"
static_files = StaticFiles(directory=str(static_dir))
