"""Server-rendered HTML routes for the review surface.

Read-only for now: the queue and a per-opening rating view both call the same domain
functions (`score_opening`, `list_openings`, etc.) as the JSON routes in `screen.api.routes`.
Submission is deferred until the Ruling data model is landed (review-shell bearing).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from screen.api.deps import get_db
from screen.api.scoring import score_opening
from screen.digest.protocol import DigesterProtocol
from screen.digest.service import digest_for_target
from screen.extract.prompt import rubric_text_for_baml
from screen.score.loader import load_scoring_config
from screen.score.types import ScoringConfig
from screen.store.repo import assertions_for_opening, get_company, get_opening, list_openings
from screen.types import Assertion, Company, Opening

Conn = Annotated[sqlite3.Connection, Depends(get_db)]

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@dataclass(frozen=True)
class _DimensionGroup:
    target: str
    digest: str
    assertions: list[Assertion]


def _company_for(conn: sqlite3.Connection, opening: Opening) -> Company:
    """`Opening.company_id` is a foreign key with `PRAGMA foreign_keys = ON`
    (store/db.py) — the referenced company always exists."""
    return cast(Company, get_company(conn, opening.company_id))


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
            )
        )
    return groups


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
    """The read-only rating surface for one opening: its score and grouped assertions."""
    opening = get_opening(conn, opening_id)
    if opening is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    company = _company_for(conn, opening)
    assertions = assertions_for_opening(conn, opening_id)
    config = load_scoring_config()
    score = score_opening(assertions, config)
    groups = _dimension_groups(
        conn,
        opening_id=opening_id,
        assertions=assertions,
        config=config,
        digester=request.app.state.digester,
        rubric_text=rubric_text_for_baml(),
        now=datetime.now(UTC),
    )
    return templates.TemplateResponse(
        request,
        "rating.html",
        {
            "opening": opening,
            "company": company,
            "groups": groups,
            "score": score,
        },
    )


# Static files: CSS, later HTMX assets, etc.
static_dir = Path(__file__).parent / "static"
static_files = StaticFiles(directory=str(static_dir))
