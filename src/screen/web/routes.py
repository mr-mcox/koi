"""Server-rendered HTML routes for the review surface.

The queue and a per-opening rating view both call the same domain functions
(`score_opening`, `list_openings`, etc.) as the JSON routes in `screen.api.routes`.
The rating view also accepts assertion-ruling submissions via HTMX partial swap
(assertion-ruling-submit bearing) — the JSON routes stay read-only and untouched.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from screen.api.deps import get_db
from screen.api.scoring import score_opening
from screen.score.loader import load_scoring_config
from screen.score.types import FIT_VALUES
from screen.store.repo import (
    assertion_rulings_for_opening,
    assertions_for_opening,
    get_company,
    get_opening,
    list_openings,
    upsert_assertion_ruling,
)
from screen.types import AssertionRuling, Company, Fit, Opening

Conn = Annotated[sqlite3.Connection, Depends(get_db)]

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _company_for(conn: sqlite3.Connection, opening: Opening) -> Company:
    """`Opening.company_id` is a foreign key with `PRAGMA foreign_keys = ON`
    (store/db.py) — the referenced company always exists."""
    return cast(Company, get_company(conn, opening.company_id))


def _queue_items(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Build the same ranked list the JSON `/queue` returns, shaped for the template."""
    config = load_scoring_config()
    items = []
    for opening in list_openings(conn):
        company = _company_for(conn, opening)
        assertions = assertions_for_opening(conn, opening.id)
        result = score_opening(assertions, config)
        items.append(
            {
                "opening_id": opening.id,
                "company_name": company.name,
                "opening_title": opening.title,
                "standing": result.standing,
                "reach": result.reach,
                "band": result.band,
                "ceiling": result.ceiling,
                "unreachable": result.unreachable,
            }
        )
    items.sort(key=lambda item: item["standing"], reverse=True)
    return items


def _latest_ruling_by_assertion(
    rulings: list[AssertionRuling],
) -> dict[str, AssertionRuling]:
    """Rulings are append-only (F26: re-rating is expected, not an error) —
    keep the most recent one per assertion for display. `assertion_rulings_for_opening`
    already orders by `created_at`, so the last write per key wins."""
    return {ruling.assertion_id: ruling for ruling in rulings}


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: Conn) -> HTMLResponse:
    """The queue view: ranked openings as HTML."""
    items = _queue_items(conn)
    return templates.TemplateResponse(request, "queue.html", {"items": items})


def _rating_context(conn: sqlite3.Connection, opening_id: str) -> dict[str, object]:
    """Everything the rating page (and its HTMX partial) render — shared so a fresh
    GET and a post-ruling swap can never drift out of agreement (Approach: HTMX swaps
    the whole rating-content block, not hand-picked sub-fragments)."""
    opening = get_opening(conn, opening_id)
    if opening is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    company = _company_for(conn, opening)
    assertions = assertions_for_opening(conn, opening_id)
    rulings = _latest_ruling_by_assertion(assertion_rulings_for_opening(conn, opening_id))
    ruled_fits: dict[str, Fit] = {
        assertion_id: ruling.fit for assertion_id, ruling in rulings.items()
    }
    score = score_opening(assertions, load_scoring_config(), rulings=ruled_fits)
    return {
        "opening": opening,
        "company": company,
        "assertions": assertions,
        "score": score,
        "rulings": rulings,
        "fit_values": list(FIT_VALUES),
    }


@router.get("/openings/{opening_id}/rate", response_class=HTMLResponse)
def rate_opening(request: Request, opening_id: str, conn: Conn) -> HTMLResponse:
    """The rating surface for one opening: its score, assertions, and any recorded
    rulings, with per-assertion override controls."""
    context = _rating_context(conn, opening_id)
    return templates.TemplateResponse(request, "rating.html", context)


@router.post("/openings/{opening_id}/assertions/{assertion_id}/ruling", response_class=HTMLResponse)
def submit_ruling(
    request: Request,
    opening_id: str,
    assertion_id: str,
    conn: Conn,
    fit: Annotated[Fit, Form()],
) -> HTMLResponse:
    """Upsert the operator's ruling for one assertion, then return the rating-content
    partial (not a full document) for an HTMX swap — F20/F31: re-sorting the queue
    itself is the separate queue page's concern, not this fragment's."""
    if get_opening(conn, opening_id) is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    upsert_assertion_ruling(
        conn,
        AssertionRuling(
            id=str(uuid4()), assertion_id=assertion_id, fit=fit, created_at=datetime.now(UTC)
        ),
    )
    context = _rating_context(conn, opening_id)
    return templates.TemplateResponse(request, "_rating_content.html", context)


# Static files: CSS, later HTMX assets, etc.
static_dir = Path(__file__).parent / "static"
static_files = StaticFiles(directory=str(static_dir))
