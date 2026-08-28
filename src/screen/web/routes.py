"""Server-rendered HTML routes for the review surface.

Read-only for now: the queue and a per-opening rating view both call the same domain
functions (`score_opening`, `list_openings`, etc.) as the JSON routes in `screen.api.routes`.
Submission is deferred until the Ruling data model is landed (review-shell bearing).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from screen.api.deps import get_db
from screen.api.scoring import score_opening
from screen.score.loader import load_scoring_config
from screen.store.repo import assertions_for_opening, get_company, get_opening, list_openings
from screen.types import Company, Opening

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


@router.get("/", response_class=HTMLResponse)
def index(request: Request, conn: Conn) -> HTMLResponse:
    """The queue view: ranked openings as HTML."""
    items = _queue_items(conn)
    return templates.TemplateResponse(request, "queue.html", {"items": items})


@router.get("/openings/{opening_id}/rate", response_class=HTMLResponse)
def rate_opening(request: Request, opening_id: str, conn: Conn) -> HTMLResponse:
    """The read-only rating surface for one opening: its score and assertions."""
    opening = get_opening(conn, opening_id)
    if opening is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    company = _company_for(conn, opening)
    assertions = assertions_for_opening(conn, opening_id)
    score = score_opening(assertions, load_scoring_config())
    return templates.TemplateResponse(
        request,
        "rating.html",
        {
            "opening": opening,
            "company": company,
            "assertions": assertions,
            "score": score,
        },
    )


# Static files: CSS, later HTMX assets, etc.
static_dir = Path(__file__).parent / "static"
static_files = StaticFiles(directory=str(static_dir))
