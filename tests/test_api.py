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
from screen.score.scorer import rank_pool
from screen.score.types import PoolInput
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


def test_opening_score_reports_pool_rank_readouts(client: TestClient, db_path: Path) -> None:
    """`/openings/{id}/score` returns the same pool-scored rank readouts the queue uses.
    With only one opening in the pool it is unambiguously rank 1 and top-K."""
    assertion = Assertion(
        target="stretch",
        fit="Strong",
        provenance="ratified",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=[assertion])
    config = load_scoring_config()
    expected = rank_pool(
        [PoolInput(opening_id="acme--eng", assertions=[assertion])],
        config,
        top_k=config.top_k,
    ).opening_ranks[0]

    response = client.get("/openings/acme--eng/score")

    assert response.status_code == 200
    body = response.json()
    assert body["opening_id"] == "acme--eng"
    assert body["company_id"] == "acme"
    assert body["company_name"] == "acme Inc"
    assert body["opening_title"] == "acme--eng title"
    assert body["p_top_k"] == pytest.approx(expected.p_top_k)
    assert body["expected_rank"] == pytest.approx(expected.expected_rank)
    assert body["rank_q10"] == pytest.approx(expected.rank_q10)
    assert body["rank_q50"] == pytest.approx(expected.rank_q50)
    assert body["rank_q90"] == pytest.approx(expected.rank_q90)
    assert body["top_k"] == config.top_k
    assert 0.0 <= body["settledness"] <= 1.0


def test_queue_is_empty_when_no_openings_exist(client: TestClient) -> None:
    response = client.get("/queue")
    assert response.status_code == 200
    assert response.json() == []


def test_queue_sorts_by_p_top_k_descending(client: TestClient, db_path: Path) -> None:
    """A well-evidenced opening should have a higher `P(rank ≤ top_k)` than an unexamined
    one, and the queue sorts on that (then expected rank, then id)."""
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
        for slug in (*config.dimension_weights,)
    ]
    _seed_opening(
        db_path, company_id="acme", opening_id="acme--strong", assertions=strong_assertions
    )
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--unexamined")

    response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    assert [item["opening_id"] for item in body] == ["acme--strong", "widgets--unexamined"]
    assert body[0]["p_top_k"] >= body[1]["p_top_k"]
    assert body[0]["expected_rank"] < body[1]["expected_rank"]


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
        for slug in (*config.dimension_weights,)
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
    queue_item = next(item for item in body if item["opening_id"] == "acme--ruled")
    score_response = client.get("/openings/acme--ruled/score").json()
    assert score_response["p_top_k"] == pytest.approx(queue_item["p_top_k"])
    assert score_response["expected_rank"] == pytest.approx(queue_item["expected_rank"])
    assert score_response["rank_q10"] == pytest.approx(queue_item["rank_q10"])
    assert score_response["rank_q50"] == pytest.approx(queue_item["rank_q50"])
    assert score_response["rank_q90"] == pytest.approx(queue_item["rank_q90"])
    assert score_response["settledness"] == pytest.approx(queue_item["settledness"])


def test_queue_includes_settledness_when_enough_openings(client: TestClient, db_path: Path) -> None:
    """With at least `top_k` openings, every queue item carries the pool's top-K
    settledness and the shared `top_k`. Seed exactly `top_k` openings so the boundary
    exists but the pool is fully separated."""
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
            for slug in (*config.dimension_weights,)
        ]
        _seed_opening(db_path, company_id=f"c{i}", opening_id=f"c{i}--eng", assertions=assertions)
    response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == config.top_k
    for item in body:
        assert "settledness" in item
        assert "top_k" in item
        assert item["top_k"] == config.top_k
        assert 0.0 <= item["settledness"] <= 1.0
    # A fully separated pool reports K/K overlap.
    assert body[0]["settledness"] == pytest.approx(1.0)


def test_queue_settledness_is_one_when_fewer_than_top_k(client: TestClient, db_path: Path) -> None:
    """Fewer than `top_k` openings: every opening is in the top K by definition, so
    settledness is 1.0."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")
    response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["settledness"] == pytest.approx(1.0)
    assert body[0]["top_k"] == load_scoring_config().top_k


def test_queue_p_top_k_is_deterministic_across_calls(client: TestClient, db_path: Path) -> None:
    """Two `/queue` calls against the same DB snapshot return identical `p_top_k`
    values — both draw under the shared `config.seed`, so this is reproducibility,
    not sampling noise."""
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
            for slug in (*config.dimension_weights,)
        ]
        _seed_opening(db_path, company_id=f"d{i}", opening_id=f"d{i}--eng", assertions=assertions)
    first = client.get("/queue").json()
    second = client.get("/queue").json()
    assert [item["p_top_k"] for item in first] == [item["p_top_k"] for item in second]
