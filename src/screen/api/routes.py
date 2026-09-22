"""HTTP routes: one opening's score, and the ranked queue across all openings.

Both compute at request time from stored assertions plus whatever `rubric.yaml`/
`scoring.yaml` say *now* — no `ScoreResult` or queue row is ever persisted, so a
`bar`/weight change can't leave a stale score behind.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from screen.api.deps import get_db
from screen.api.pool import rank_screening_pool
from screen.score.loader import load_scoring_config
from screen.score.types import OpeningRank
from screen.store.repo import (
    get_company,
    get_opening,
    list_openings,
)
from screen.types import Company, Opening

Conn = Annotated[sqlite3.Connection, Depends(get_db)]

router = APIRouter()


class ScoreResponse(BaseModel):
    opening_id: str
    company_id: str
    company_name: str
    opening_title: str
    p_top_k: float
    expected_rank: float
    rank_q10: float
    rank_q50: float
    rank_q90: float
    top_k: int
    settledness: float


def _to_response(
    company: Company,
    opening: Opening,
    rank: OpeningRank,
    *,
    top_k: int,
    settledness: float,
) -> ScoreResponse:
    return ScoreResponse(
        opening_id=opening.id,
        company_id=company.id,
        company_name=company.name,
        opening_title=opening.title,
        p_top_k=rank.p_top_k,
        expected_rank=rank.expected_rank,
        rank_q10=rank.rank_q10,
        rank_q50=rank.rank_q50,
        rank_q90=rank.rank_q90,
        top_k=top_k,
        settledness=settledness,
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
    config = load_scoring_config()

    # Score the live screening pool, but make sure the requested opening has a rank even
    # if it has already left the `screening` stage (the rating view may still be open).
    openings = list({o.id: o for o in [*list_openings(conn, stage="screening"), opening]}.values())

    result = rank_screening_pool(conn, config, openings=openings)
    rank = next(r for r in result.opening_ranks if r.opening_id == opening_id)
    return _to_response(company, opening, rank, top_k=result.top_k, settledness=result.settledness)


@router.get("/queue", response_model=list[ScoreResponse])
def get_queue(conn: Conn) -> list[ScoreResponse]:
    config = load_scoring_config()
    openings = list_openings(conn, stage="screening")
    result = rank_screening_pool(conn, config, openings=openings)
    ranks_by_id = {r.opening_id: r for r in result.opening_ranks}

    responses = [
        _to_response(
            _company_for(conn, o),
            o,
            ranks_by_id[o.id],
            top_k=result.top_k,
            settledness=result.settledness,
        )
        for o in openings
    ]
    responses.sort(key=lambda r: (-r.p_top_k, r.expected_rank, r.opening_id))
    return responses
