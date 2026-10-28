"""The ranked queue and the per-opening rating view. Both rank through the same
`rank_screening_pool` the JSON `/queue` uses; the rating view accepts assertion rulings
via an HTMX partial swap."""

import sqlite3
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from screen.api.deps import app_deps, app_state
from screen.digest.protocol import DigesterProtocol
from screen.pool import latest_ruling_by_assertion, rank_screening_pool
from screen.score.loader import load_scoring_config
from screen.score.types import FIT_VALUES
from screen.store.repo import (
    assertion_rulings_for_opening,
    assertions_for_opening,
    get_opening,
    list_openings,
    upsert_assertion_ruling,
)
from screen.types import AssertionRuling, Fit
from screen.web.common import (
    Conn,
    accent_hues,
    boundary_glyph_for_score,
    company_for,
    dimension_groups,
    templates,
)

router = APIRouter()


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
    for i, rank in enumerate(ordered):
        opening = openings_by_id[rank.opening_id]
        company = company_for(conn, opening)
        company_hue, opening_hue = accent_hues(company.id, opening.id)

        age_days = (datetime.now(UTC) - opening.created_at).days
        threshold = max(14, 28 - i)
        is_stale = age_days > threshold
        items.append(
            {
                "opening_id": opening.id,
                "company_name": company.name,
                "opening_title": opening.title,
                "company_hue": company_hue,
                "opening_hue": opening_hue,
                "glyph": boundary_glyph_for_score(
                    rank,
                    top_k=result.top_k,
                    total=len(result.opening_ids),
                ),
                "p_top_k": rank.p_top_k,
                "is_stale": is_stale,
                "age_days": age_days,
            }
        )
    return items


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: Conn) -> HTMLResponse:
    """The queue view: ranked openings as HTML."""
    items = _queue_items(conn)
    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "items": items,
            "status": app_state(request).batch,
        },
    )


@router.post("/prune-stale", response_class=RedirectResponse)
def prune_stale(conn: Conn) -> RedirectResponse:
    """Move all stale openings in the screening queue to 'closed' in one batch."""
    stale_items = [item for item in _queue_items(conn) if item["is_stale"]]
    for item in stale_items:
        conn.execute("UPDATE openings SET stage = ? WHERE id = ?", ("closed", item["opening_id"]))
    conn.commit()
    return RedirectResponse(url="/", status_code=303)


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
    company = company_for(conn, opening)
    assertions = assertions_for_opening(conn, opening_id)
    rulings = latest_ruling_by_assertion(assertion_rulings_for_opening(conn, opening_id))
    config = load_scoring_config()
    result = rank_screening_pool(conn, config)
    rank = next(r for r in result.opening_ranks if r.opening_id == opening_id)
    company_hue, opening_hue = accent_hues(company.id, opening_id)
    groups = dimension_groups(
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
        "score_glyph": boundary_glyph_for_score(
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
    """`_rating_context` with the app's digester and rubric — shared by the GET and the
    assertion-ruling-submit route."""
    return _rating_context(
        conn,
        opening_id,
        digester=app_deps(request).digester,
        rubric_text=app_deps(request).rubric.full(),
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
