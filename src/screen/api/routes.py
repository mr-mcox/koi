"""HTTP routes: one opening's score, and the ranked queue across all openings.

Both compute at request time from stored assertions plus whatever `rubric.yaml`/
`scoring.yaml` say *now* (bearing.md's Approach) — no `ScoreResult` or queue row
is ever persisted, so a `bar`/weight change can't leave a stale score behind.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from screen.api.deps import get_db
from screen.api.scoring import OpeningScore, score_opening
from screen.score.loader import load_scoring_config
from screen.store.repo import assertions_for_opening, get_company, get_opening, list_openings
from screen.types import Company, Opening

Conn = Annotated[sqlite3.Connection, Depends(get_db)]

router = APIRouter()


class ScoreResponse(BaseModel):
    opening_id: str
    company_id: str
    company_name: str
    opening_title: str
    standing: float
    reach: float
    band: str
    ceiling: float
    unreachable: bool


def _to_response(company: Company, opening: Opening, result: OpeningScore) -> ScoreResponse:
    return ScoreResponse(
        opening_id=opening.id,
        company_id=company.id,
        company_name=company.name,
        opening_title=opening.title,
        standing=result.standing,
        reach=result.reach,
        band=result.band,
        ceiling=result.ceiling,
        unreachable=result.unreachable,
    )


def _company_for(conn: sqlite3.Connection, opening: Opening) -> Company:
    """`Opening.company_id` is a foreign key with `PRAGMA foreign_keys = ON`
    (store/db.py) — the referenced company always exists."""
    return cast(Company, get_company(conn, opening.company_id))


@router.get("/openings/{opening_id}/score", response_model=ScoreResponse)
def get_opening_score(opening_id: str, conn: Conn) -> ScoreResponse:
    opening = get_opening(conn, opening_id)
    if opening is None:
        raise HTTPException(status_code=404, detail=f"no such opening: {opening_id}")
    company = _company_for(conn, opening)
    assertions = assertions_for_opening(conn, opening_id)
    result = score_opening(assertions, load_scoring_config())
    return _to_response(company, opening, result)


@router.get("/queue", response_model=list[ScoreResponse])
def get_queue(conn: Conn) -> list[ScoreResponse]:
    config = load_scoring_config()
    items = []
    for opening in list_openings(conn):
        company = _company_for(conn, opening)
        assertions = assertions_for_opening(conn, opening.id)
        result = score_opening(assertions, config)
        items.append(_to_response(company, opening, result))
    # Standing is the only sort key (S5 · reach never sorts).
    items.sort(key=lambda item: item.standing, reverse=True)
    return items
