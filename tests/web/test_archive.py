"""Integration tests for stage changes and the archive view."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from screen.store.repo import (
    get_opening,
)
from tests.helpers import seed_opening


def test_submit_stage_change_updates_opening_and_redirects_to_queue(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Posting a new stage for an opening persists it and leaves the rating view (the
    operator's request: a lightweight marker, not a full application tracker)."""
    seed_opening(conn, "acme--eng")

    response = client.post(
        "/openings/acme--eng/stage", data={"stage": "pursuing"}, follow_redirects=False
    )

    assert response.status_code in (302, 303)
    opening = get_opening(conn, "acme--eng")
    assert opening is not None
    assert opening.stage == "pursuing"


def test_submit_stage_change_rejects_unknown_stage(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    seed_opening(conn, "acme--eng")

    response = client.post("/openings/acme--eng/stage", data={"stage": "ghosted"})

    assert response.status_code == 422


def test_submit_stage_change_404s_for_unknown_opening(client: TestClient) -> None:
    response = client.post("/openings/does-not-exist/stage", data={"stage": "applied"})
    assert response.status_code == 404


def test_rating_view_shows_stage_controls(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The rating view exposes a way to change an opening's stage — the same page the
    operator already reviews the opening from."""
    seed_opening(conn, "acme--eng")

    response = client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    assert "/openings/acme--eng/stage" in response.text
    for stage in ("screening", "pursuing", "applied", "closed"):
        assert stage in response.text


def test_archive_view_lists_openings_by_stage(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """`/archive` lists every non-`screening` opening, filterable by stage, each linking
    back to its existing rating view for recall."""
    seed_opening(conn, "acme--screening")
    seed_opening(conn, "widgets--pursuing", stage="pursuing")
    seed_opening(conn, "globex--applied", stage="applied")
    seed_opening(conn, "initech--closed", stage="closed")

    response = client.get("/archive")

    assert response.status_code == 200
    body = response.text
    assert "acme--screening" not in body
    assert "widgets--pursuing" in body
    assert "globex--applied" in body
    assert "initech--closed" in body
    assert "/openings/widgets--pursuing/rate" in body


def test_archive_view_filters_to_one_stage_via_query_param(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    seed_opening(conn, "widgets--pursuing", stage="pursuing")
    seed_opening(conn, "globex--applied", stage="applied")

    response = client.get("/archive", params={"stage": "applied"})

    assert response.status_code == 200
    body = response.text
    assert "globex--applied" in body
    assert "widgets--pursuing" not in body


def test_index_links_to_archive(client: TestClient) -> None:
    """The queue page links to `/archive` — the operator's way to reach filtered stages."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/archive"' in response.text
