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
from screen.store.repo import (
    append_assertions,
    upsert_assertion_ruling,
    upsert_company,
    upsert_opening,
)
from screen.types import Assertion, AssertionRuling, Citation, Company, Opening

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
            research_turns_budget=5,
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


def test_queue_and_score_apply_assertion_rulings(client: TestClient, db_path: Path) -> None:
    """Rulings must move the queue: an opening with Poor model-proposed assertions that
    are all overridden to Strong should outrank an unexamined one, and the per-opening
    score endpoint must agree with the queue entry."""
    config = load_scoring_config()
    weak_assertions = [
        Assertion(
            target=slug,  # type: ignore[arg-type]
            fit="Poor",
            provenance="model_proposed",
            chunk="verbatim source text",
            citations=[_CITATION],
            created_at=_NOW,
        )
        for slug in (*config.dimension_weights, *config.constraints)
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--ruled", assertions=weak_assertions)
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--unexamined")

    conn = connect(db_path)
    for assertion in weak_assertions:
        upsert_assertion_ruling(
            conn,
            AssertionRuling(
                id=f"ruling--{assertion.id}",
                assertion_id=assertion.id,
                fit="Strong",
                created_at=_NOW,
            ),
        )
    conn.close()

    response = client.get("/queue")
    assert response.status_code == 200
    body = response.json()
    assert [item["opening_id"] for item in body] == ["acme--ruled", "widgets--unexamined"]

    score_response = client.get("/openings/acme--ruled/score").json()
    queue_item = next(item for item in body if item["opening_id"] == "acme--ruled")
    assert score_response["standing"] == pytest.approx(queue_item["standing"])
    assert score_response["reach"] == pytest.approx(queue_item["reach"])
    assert score_response["ceiling"] == pytest.approx(queue_item["ceiling"])
    assert score_response["unreachable"] == queue_item["unreachable"]


def test_queue_includes_crossing_probability_when_enough_openings(
    client: TestClient, db_path: Path
) -> None:
    """With at least `top_k` openings, every queue item carries a
    `crossing_probability` computed against the K-th-ranked opening's trace under the
    shared `config.seed`. `scoring.yaml`'s real `top_k` is 10; seed exactly that many
    openings at strictly decreasing standing so rank K is unambiguous."""
    config = load_scoring_config()
    for i in range(config.top_k):
        assertions = [
            Assertion(
                target=slug,  # type: ignore[arg-type]
                fit="Strong" if i == 0 else "Poor",
                provenance="ratified",
                chunk="verbatim source text",
                citations=[_CITATION],
                created_at=_NOW,
            )
            for slug in (*config.dimension_weights, *config.constraints)
        ]
        _seed_opening(db_path, company_id=f"c{i}", opening_id=f"c{i}--eng", assertions=assertions)

    response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == config.top_k
    for item in body:
        assert "crossing_probability" in item
        assert 0.0 <= item["crossing_probability"] <= 1.0
    # The K-th-ranked opening (last in the sorted list) always crosses itself.
    assert body[-1]["crossing_probability"] == pytest.approx(0.0)


def test_queue_omits_crossing_probability_when_fewer_than_top_k(
    client: TestClient, db_path: Path
) -> None:
    """Fewer than `top_k` openings: no K-th opening exists, so `crossing_probability`
    is omitted rather than defaulting to 0 or 1 — a small backlog isn't "everyone
    stable," it's "the boundary doesn't exist yet." """
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["crossing_probability"] is None


def test_queue_crossing_probability_is_deterministic_across_calls(
    client: TestClient, db_path: Path
) -> None:
    """Two `/queue` calls against the same DB snapshot return identical
    `crossing_probability` values — both draw under the shared `config.seed`, so this
    is reproducibility, not sampling noise."""
    config = load_scoring_config()
    for i in range(config.top_k):
        assertions = [
            Assertion(
                target=slug,  # type: ignore[arg-type]
                fit="Strong" if i == 0 else "Poor",
                provenance="ratified",
                chunk="verbatim source text",
                citations=[_CITATION],
                created_at=_NOW,
            )
            for slug in (*config.dimension_weights, *config.constraints)
        ]
        _seed_opening(db_path, company_id=f"d{i}", opening_id=f"d{i}--eng", assertions=assertions)

    first = client.get("/queue").json()
    second = client.get("/queue").json()

    assert [item["crossing_probability"] for item in first] == [
        item["crossing_probability"] for item in second
    ]
