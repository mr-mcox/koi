"""Server-rendered HTML routes for the review surface.
The queue and a per-opening rating view both call the same pool-scored domain
functions (`pool_for_screening`, `list_openings`, etc.) as the JSON routes in
`screen.api.routes`. The rating view accepts assertion-ruling submissions via an
HTMX partial swap — the JSON routes stay read-only and untouched.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from screen.api.deps import get_db
from screen.api.pool import rank_screening_pool, suggest_next_comparison
from screen.api.scoring import latest_ruling_by_assertion
from screen.digest.protocol import DigesterProtocol
from screen.digest.render import render_digest_html
from screen.digest.service import digest_for_target
from screen.extract.prompt import rubric_text_for_baml
from screen.research.batch import eta_text
from screen.score.compare_probability import pre_comparison_probability
from screen.score.loader import load_scoring_config
from screen.score.scorer import stats_for_target
from screen.score.types import FIT_VALUES, OpeningRank, ScoringConfig
from screen.store.repo import (
    append_comparison,
    assertion_rulings_for_opening,
    assertions_for_opening,
    enqueue_intake_url,
    get_company,
    get_opening,
    list_intake_queue,
    list_openings,
    reset_intake_url_to_pending,
    upsert_assertion_ruling,
    upsert_opening,
)
from screen.types import (
    Assertion,
    AssertionRuling,
    Company,
    Comparison,
    ComparisonOutcome,
    Fit,
    Opening,
    Stage,
    Target,
)

Conn = Annotated[sqlite3.Connection, Depends(get_db)]

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["render_digest_html"] = render_digest_html
templates.env.filters["eta_text"] = eta_text


@dataclass(frozen=True)
class _DimensionGroup:
    target: str
    digest: str
    assertions: list[Assertion]


@dataclass(frozen=True)
class BoundaryGlyph:
    """Rank-axis credible-interval bar for one opening in the pool: `low`/`median`/`high`
    are sampled rank quantiles (lower rank is better), and `boundary` is the `top_k`
    cutoff. Percentages are computed against a shared axis so rows are comparable: left
    is best, right is worse. `settledness_alpha`/`settledness_label` say whether the band
    is fully inside the boundary, straddling it, or fully outside — the per-opportunity
    replacement for a global settledness readout."""

    low: float
    median: float
    high: float
    boundary: float | None
    top_k: int
    total: int

    @property
    def _axis_max(self) -> float:
        return float(max(self.total, self.top_k * 2, 3))

    def _pct(self, rank: float) -> float:
        return (self._axis_max - rank) / (self._axis_max - 1.0)

    @property
    def low_pct(self) -> float:
        return self._pct(self.low)

    @property
    def median_pct(self) -> float:
        return self._pct(self.median)

    @property
    def high_pct(self) -> float:
        return self._pct(self.high)

    @property
    def boundary_pct(self) -> float | None:
        return self._pct(self.boundary) if self.boundary is not None else None

    @property
    def settledness_alpha(self) -> float:
        """Fill opacity for the median marker: fully opaque when the whole plausible
        rank band is inside the top-K boundary, faint when it straddles, outline-only
        when even the best plausible case is outside."""
        boundary = self.boundary
        if boundary is None:
            return 1.0
        if self.low <= boundary and self.high <= boundary:
            return 1.0
        if self.high <= boundary < self.low:
            return 0.60
        return 0.0

    @property
    def settledness_label(self) -> str:
        boundary = self.boundary
        if boundary is None:
            return "no boundary yet; rank still takes shape"
        if self.low <= boundary and self.high <= boundary:
            return f"locked into top {int(boundary)}"
        if self.high <= boundary < self.low:
            return f"contesting the top {int(boundary)} boundary"
        return f"outside the top {int(boundary)}"


def _boundary_glyph_for_score(
    rank: OpeningRank,
    *,
    top_k: int,
    total: int,
) -> BoundaryGlyph:
    """The glyph for one opening, given the pool's shared `top_k` boundary and size."""
    boundary = float(top_k) if total >= top_k else None
    return BoundaryGlyph(
        low=rank.rank_q90,
        median=rank.rank_q50,
        high=rank.rank_q10,
        boundary=boundary,
        top_k=top_k,
        total=total,
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


def _should_swap_display_order(opening_a_id: str, opening_b_id: str, target: str) -> bool:
    """Whether the comparison preview should show B on the left. Deterministic (a hash
    of the pair + target, not a stateless coin flip) so re-rendering the same comparison
    — e.g. after editing a ruling — doesn't shuffle sides mid-review, while which pair
    lands on which side is still unpredictable to the operator across different
    comparisons (so left isn't always A)."""
    digest = hashlib.sha256(f"{opening_a_id}|{opening_b_id}|{target}".encode()).digest()
    return digest[0] % 2 == 1


def _dimension_groups(
    conn: sqlite3.Connection,
    opening_id: str,
    assertions: list[Assertion],
    config: ScoringConfig,
    *,
    digester: DigesterProtocol,
    rubric_text: str,
    now: datetime,
) -> list[_DimensionGroup]:
    """Group assertions by rubric target and attach the cached digest for each group.
    Dimensions are ordered by their declared weight descending (ties broken by slug). Any
    non-scoring targets with assertions are appended after. Empty scoring targets still
    render with a 'not yet examined' digest so the operator can see coverage gaps at a
    glance.
    """
    declared = sorted(
        config.dimension_weights,
        key=lambda slug: (-config.dimension_weights[slug], slug),
    )
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
            )
        )
    return groups


def _queue_items(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Build the same ranked list the JSON `/queue` returns, shaped for the template."""
    config = load_scoring_config()
    openings = list_openings(conn, stage="screening")
    openings_by_id = {o.id: o for o in openings}
    result = rank_screening_pool(conn, config)
    ordered = sorted(
        result.opening_ranks,
        key=lambda r: (-r.p_top_k, r.expected_rank, r.opening_id),
    )
    items = []
    for rank in ordered:
        opening = openings_by_id[rank.opening_id]
        company = _company_for(conn, opening)
        company_hue, opening_hue = _accent_hues(company.id, opening.id)
        items.append(
            {
                "opening_id": opening.id,
                "company_name": company.name,
                "opening_title": opening.title,
                "company_hue": company_hue,
                "opening_hue": opening_hue,
                "glyph": _boundary_glyph_for_score(
                    rank,
                    top_k=result.top_k,
                    total=len(result.opening_ids),
                ),
                "p_top_k": rank.p_top_k,
            }
        )
    return items


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: Conn) -> HTMLResponse:
    """The queue view: ranked openings as HTML."""
    items = _queue_items(conn)
    status = request.app.state.batch_status
    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "items": items,
            "status": status,
        },
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
    config = load_scoring_config()
    result = rank_screening_pool(conn, config)
    rank = next(r for r in result.opening_ranks if r.opening_id == opening_id)
    company_hue, opening_hue = _accent_hues(company.id, opening_id)
    groups = _dimension_groups(
        conn,
        opening_id=opening_id,
        assertions=assertions,
        config=config,
        digester=digester,
        rubric_text=rubric_text,
        now=now,
    )
    return {
        "opening": opening,
        "company": company,
        "groups": groups,
        "score_glyph": _boundary_glyph_for_score(
            rank,
            top_k=result.top_k,
            total=len(result.opening_ids),
        ),
        "rulings": rulings,
        "fit_values": list(FIT_VALUES),
        "company_hue": company_hue,
        "opening_hue": opening_hue,
    }


def _rating_context_for_request(
    request: Request, conn: sqlite3.Connection, opening_id: str
) -> dict[str, object]:
    """Thin wrapper pulling the digester off `request.app.state` — shared by the GET
    and the assertion-ruling-submit route so each doesn't repeat the same three
    keyword args."""
    return _rating_context(
        conn,
        opening_id,
        digester=request.app.state.digester,
        rubric_text=rubric_text_for_baml(),
        now=datetime.now(UTC),
    )


@router.get("/openings/{opening_id}/rate", response_class=HTMLResponse)
def rate_opening(request: Request, opening_id: str, conn: Conn) -> HTMLResponse:
    """The rating surface for one opening: its score, dimension-grouped assertions
    (each with a cached digest), and any recorded rulings, with per-assertion
    override controls."""
    context = _rating_context_for_request(request, conn, opening_id)
    return templates.TemplateResponse(request, "rating.html", context)


@router.post(
    "/openings/{opening_id}/assertions/{assertion_id}/ruling",
    response_model=None,
)
def submit_ruling(
    *,
    request: Request,
    opening_id: str,
    assertion_id: str,
    conn: Conn,
    fit: Annotated[Fit, Form()],
    redirect_to: Annotated[str | None, Form()] = None,
) -> HTMLResponse | RedirectResponse:
    """Upsert the operator's ruling for one assertion. By default returns the
    rating-content partial for an HTMX swap (the rating page's flow: submitting a
    rating must re-sort the queue without a full page reload). `redirect_to` lets a
    non-HTMX caller — the compare page, where a ruling submitted from either column
    isn't scoped to one `#rating-content` element — send the operator back to a
    specific page instead; only same-origin relative paths are honored."""
    if get_opening(conn, opening_id) is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    upsert_assertion_ruling(
        conn,
        AssertionRuling(
            id=str(uuid4()), assertion_id=assertion_id, fit=fit, created_at=datetime.now(UTC)
        ),
    )
    if redirect_to is not None and redirect_to.startswith("/") and not redirect_to.startswith("//"):
        return RedirectResponse(redirect_to, status_code=303)
    context = _rating_context_for_request(request, conn, opening_id)
    return templates.TemplateResponse(request, "_rating_content.html", context)


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
    comparison surface reuses the same `_dimension_groups` the rating view uses, but
    only keeps the group for the selected target. Display order (left/right) is a
    deterministic function of the pair and target, not always A-on-the-left, so the
    operator can't infer which opening is "A" from position alone; it stays stable
    across reloads of the same pair (e.g. after editing a ruling) since it isn't a
    fresh coin flip each render."""
    opening_a_id, opening_b_id = opening_a.id, opening_b.id
    swapped = _should_swap_display_order(opening_a_id, opening_b_id, target)
    opening_left, opening_right = (opening_b, opening_a) if swapped else (opening_a, opening_b)

    def _group(opening_id: str) -> _DimensionGroup | None:
        groups = _dimension_groups(
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
    return {
        "target": target,
        "opening_left": opening_left,
        "opening_right": opening_right,
        "group_left": _group(opening_left.id),
        "group_right": _group(opening_right.id),
        "rulings_left": _rulings(opening_left.id),
        "rulings_right": _rulings(opening_right.id),
        "outcome_left": "b" if swapped else "a",
        "outcome_right": "a" if swapped else "b",
        "fit_values": list(FIT_VALUES),
        "redirect_url": redirect_url,
        "predicted_a_beats_b": pre_comparison_probability(
            stats_a.mean, stats_a.half_width, stats_b.mean, stats_b.half_width
        ),
    }


@router.get("/compare", response_class=HTMLResponse)
def compare(
    request: Request,
    conn: Conn,
    opening_a_id: str | None = None,
    opening_b_id: str | None = None,
    target: str | None = None,
) -> HTMLResponse:
    """Comparison surface: the backend picker chooses the pair/dimension by default, the
    operator judges it, and the screen immediately hands over the next one — there is no
    operator-facing selection UI. The three query parameters are not linked from anywhere
    in the UI; they exist only so a specific pair can be reached directly (fixtures,
    debugging, a bookmarked link), and when given they still render through the same
    preview/redirect path the picker uses."""
    config = load_scoring_config()
    if not (opening_a_id and opening_b_id and target):
        suggestion = suggest_next_comparison(conn, config)
        if suggestion is None:
            opening_a_id = opening_b_id = target = None
        else:
            opening_a_id = suggestion.opening_a_id
            opening_b_id = suggestion.opening_b_id
            target = suggestion.target
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
                digester=request.app.state.digester,
                rubric_text=rubric_text_for_baml(),
                now=datetime.now(UTC),
                redirect_url=redirect_url,
            )
        )
    return templates.TemplateResponse(request, "compare.html", context)


@router.post("/compare")
def submit_comparison(
    conn: Conn,
    opening_a_id: Annotated[str, Form()],
    opening_b_id: Annotated[str, Form()],
    target: Annotated[str, Form()],
    outcome: Annotated[str, Form()],
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
            created_at=datetime.now(UTC),
        ),
    )
    return RedirectResponse("/compare", status_code=303)


STAGES: tuple[Stage, ...] = ("screening", "pursuing", "applied", "closed")


@router.post("/openings/{opening_id}/stage")
def submit_stage(
    opening_id: str,
    conn: Conn,
    stage: Annotated[Stage, Form()],
) -> RedirectResponse:
    """Move an opening to a new pipeline stage. A lightweight
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
    it stops being ranked. Unranked: display order is stage then company, never
    standing."""
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
    batch_size: Annotated[int, Form(gt=0)] = 50,
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
        "started_at": None,
        "rate": None,
        "eta_seconds": None,
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


@router.post("/intake-queue", response_class=HTMLResponse)
def post_intake_queue(
    request: Request, conn: Conn, url: Annotated[str, Form(min_length=1)]
) -> HTMLResponse:
    """Enqueue one URL for the background intake worker. The insert commits
    before this returns (bearing: queuing is blocking, minimizing lost work) —
    the worker (started once in the app lifespan) picks it up on its own,
    including a URL added while it's mid-batch."""
    enqueue_intake_url(conn, url)
    items = list_intake_queue(conn)
    return templates.TemplateResponse(request, "_intake_queue_list.html", {"items": items})


@router.post("/intake-queue/{item_id}/retry", response_class=HTMLResponse)
def retry_intake_url(request: Request, conn: Conn, item_id: str) -> HTMLResponse:
    """Requeue one failed row as pending; the always-on worker picks it up
    on its next poll. A no-op if the row isn't `failed` (e.g. a stale button
    click after the row already advanced)."""
    reset_intake_url_to_pending(conn, item_id)
    items = list_intake_queue(conn)
    return templates.TemplateResponse(request, "_intake_queue_list.html", {"items": items})


@router.get("/intake-queue", response_class=HTMLResponse)
def intake_queue(request: Request, conn: Conn) -> HTMLResponse:
    """The intake queue page: submit a URL, see every queued/running/done/failed
    row and its failure reason — the only intake surface (CLI retired)."""
    items = list_intake_queue(conn)
    return templates.TemplateResponse(request, "intake_queue.html", {"items": items})


# Static files: CSS, later HTMX assets, etc.
static_dir = Path(__file__).parent / "static"
static_files = StaticFiles(directory=str(static_dir))
