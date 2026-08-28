"""Integration tests for the FastAPI API surface.

Uses `TestClient` against the app factory so each test gets an isolated
SQLite database in a temporary directory, seeded directly via `screen.store.repo`
(the same interface the CLI writes through) rather than via HTTP.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from screen.api.app import create_app
from screen.score.loader import load_scoring_config
from screen.score.scorer import score
from screen.store.db import connect
from screen.store.repo import append_assertions, upsert_company, upsert_opening
from screen.types import Assertion, Citation, Company, Opening

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "screen.db"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    """A TestClient backed by a fresh database at a temporary path.
    Used as a context manager so lifespan (and its `Database.connect()` call) runs."""
    app = create_app(db_path)
    with TestClient(app) as test_client:
        yield test_client


def _seed_opening(
    db_path: Path, *, company_id: str, opening_id: str, assertions: list[Assertion] | None = None
) -> None:
    conn = connect(db_path)
    upsert_company(conn, Company(id=company_id, name=f"{company_id} Inc", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title=f"{opening_id} title",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            created_at=_NOW,
        ),
    )
    if assertions:
        append_assertions(conn, assertions, opening_id=opening_id)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_opening_score_returns_404_when_opening_missing(client: TestClient) -> None:
    response = client.get("/openings/no-such-opening/score")
    assert response.status_code == 404


def test_opening_score_matches_direct_scorer_call(client: TestClient, db_path: Path) -> None:
    assertion = Assertion(
        target="stretch",
        fit="Strong",
        provenance="ratified",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=[assertion])

    response = client.get("/openings/acme--eng/score")

    assert response.status_code == 200
    body = response.json()
    assert body["opening_id"] == "acme--eng"
    assert body["company_id"] == "acme"
    assert body["company_name"] == "acme Inc"
    assert body["opening_title"] == "acme--eng title"
    expected = score([assertion], load_scoring_config())
    assert body["standing"] == pytest.approx(expected.standing)
    assert body["ceiling"] == pytest.approx(expected.ceiling)
    assert body["band"] in {"no path", "contender", "established", "capped", "wide open"}


def test_queue_is_empty_when_no_openings_exist(client: TestClient) -> None:
    response = client.get("/queue")
    assert response.status_code == 200
    assert response.json() == []


def test_queue_sorts_by_standing_descending(client: TestClient, db_path: Path) -> None:
    """A well-evidenced opening (strong, ratified assertions across every target) must
    outrank an unexamined one — sort order matches direct `score()` calls."""
    config = load_scoring_config()
    strong_assertions = [
        Assertion(
            target=slug,  # type: ignore[arg-type]
            fit="Strong",
            provenance="ratified",
            chunk="verbatim source text",
            citations=[_CITATION],
            created_at=_NOW,
        )
        for slug in (*config.dimension_weights, *config.constraints)
    ]
    _seed_opening(
        db_path, company_id="acme", opening_id="acme--strong", assertions=strong_assertions
    )
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--unexamined")

    response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    assert [item["opening_id"] for item in body] == ["acme--strong", "widgets--unexamined"]
    expected_strong = score(strong_assertions, config).standing
    expected_unexamined = score([], config).standing
    assert body[0]["standing"] == pytest.approx(expected_strong)
    assert body[1]["standing"] == pytest.approx(expected_unexamined)
    assert body[0]["standing"] >= body[1]["standing"]
