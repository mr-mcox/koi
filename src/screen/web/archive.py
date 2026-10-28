"""Pipeline stage changes and the archive of openings that have left the live queue."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from screen.store.repo import get_opening, list_openings, upsert_opening
from screen.types import Stage
from screen.web.common import Conn, accent_hues, company_for, templates

router = APIRouter()

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
            company = company_for(conn, opening)
            company_hue, opening_hue = accent_hues(company.id, opening.id)
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
