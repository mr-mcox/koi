"""Integration tests for the server-rendered HTML review surface."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from screen.api.app import create_app
from screen.digest.fakes import FakeDigester
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    upsert_company,
    upsert_dimension_digest,
    upsert_opening,
)
from screen.types import Assertion, Citation, Company, Fit, Opening, Target

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
    """A TestClient backed by a fresh database at a temporary path."""
    app = create_app(db_path, digester=FakeDigester(["Synthetic digest."]))
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


def _assertion(target: Target, fit: Fit) -> Assertion:
    return Assertion(
        target=target,
        fit=fit,
        provenance="ratified",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )


def test_rate_opening_makes_no_live_digest_calls_when_cache_is_warm(db_path: Path) -> None:
    """A warm cache means the rating view never calls the digester (Done When #2 of
    digest-latency-and-style) — cold-cache generation happens post-pass, not on page view."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="stretch",
        digest="High-bar stretch culture.",
        assertion_count=1,
        computed_at=_NOW,
    )
    conn.close()
    digester = FakeDigester(["unused"])
    app = create_app(db_path, digester=digester)

    with TestClient(app) as test_client:
        response = test_client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    assert digester.calls == 0


def test_index_renders_queue_html(client: TestClient, db_path: Path) -> None:
    """`GET /` returns text/html with the ranked queue."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "acme Inc" in body
    assert "acme--eng title" in body
    assert "rate" in body


def test_index_order_matches_json_queue(client: TestClient, db_path: Path) -> None:
    """The HTML queue renders in the same standing order as `GET /queue`."""
    config = load_scoring_config()
    strong = [
        _assertion(slug, "Strong") for slug in (*config.dimension_weights, *config.constraints)
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--strong", assertions=strong)
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--unexamined")

    html_response = client.get("/")
    json_response = client.get("/queue")

    assert html_response.status_code == 200
    assert json_response.status_code == 200
    html_body = html_response.text
    json_ids = [item["opening_id"] for item in json_response.json()]
    expected_ids = ["acme--strong", "widgets--unexamined"]
    assert json_ids == expected_ids

    # Positions in the HTML body should reflect the same order.
    positions = [html_body.find(opening_id) for opening_id in expected_ids]
    assert all(p > 0 for p in positions)
    assert positions[0] < positions[1]


def test_index_empty_queue_renders(client: TestClient) -> None:
    """An empty queue still returns a valid HTML document."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text


def test_rate_opening_renders_assertions(client: TestClient, db_path: Path) -> None:
    """`GET /openings/{id}/rate` is a distinct read-only rating surface."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "acme Inc" in body
    assert "acme--eng title" in body
    assert "stretch" in body
    assert "Strong" in body
    assert "Back to queue" in body


def test_rate_opening_groups_assertions_by_dimension(client: TestClient, db_path: Path) -> None:
    """Assertions are grouped under their target dimension heading instead of a flat list."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[
            _assertion("stretch", "Strong"),
            _assertion("mission", "Mixed"),
        ],
    )

    response = client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    body = response.text
    assert '<h3 class="dimension-title">stretch</h3>' in body
    assert '<h3 class="dimension-title">mission</h3>' in body
    # Each dimension's assertion appears in its own section.
    stretch_heading = body.index('<h3 class="dimension-title">stretch</h3>')
    mission_heading = body.index('<h3 class="dimension-title">mission</h3>')
    next_after_stretch = body.find('<h3 class="dimension-title">', stretch_heading + 1)
    stretch_section = body[stretch_heading:next_after_stretch]
    assert '<span class="chip fit">Strong</span>' in stretch_section
    next_after_mission = body.find('<h3 class="dimension-title">', mission_heading + 1)
    mission_section = body[mission_heading:next_after_mission]
    assert '<span class="chip fit">Mixed</span>' in mission_section


def test_rate_opening_shows_cached_digest_above_assertions(
    client: TestClient, db_path: Path
) -> None:
    """Each dimension group shows its cached digest above the assertion list."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="stretch",
        digest="High-bar stretch culture.",
        assertion_count=1,
        computed_at=_NOW,
    )
    conn.close()

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert body.count("High-bar stretch culture.") == 1
    digest_pos = body.find("High-bar stretch culture.")
    chunk_pos = body.find("verbatim source text")
    assert digest_pos < chunk_pos


def test_rate_opening_dimension_order_is_weight_descending(
    client: TestClient, db_path: Path
) -> None:
    """Dimension groups render in weight-descending order, not assertion insertion order."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[
            _assertion("domain", "Mixed"),  # weight 1
            _assertion("stretch", "Strong"),  # weight 3
        ],
    )
    conn = connect(db_path)
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="stretch",
        digest="Stretch digest.",
        assertion_count=1,
        computed_at=_NOW,
    )
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="domain",
        digest="Domain digest.",
        assertion_count=1,
        computed_at=_NOW,
    )
    conn.close()

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert body.count("Stretch digest.") == 1
    assert body.count("Domain digest.") == 1
    assert body.find("Stretch digest.") < body.find("Domain digest.")


def test_rate_opening_empty_dimension_shows_not_yet_examined(
    client: TestClient, db_path: Path
) -> None:
    """A dimension with no assertions renders its group with a 'not yet examined' digest."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="stretch",
        digest="Stretch digest.",
        assertion_count=1,
        computed_at=_NOW,
    )
    conn.close()

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    mission_heading = body.index('<h3 class="dimension-title">mission</h3>')
    next_after_mission = body.find('<h3 class="dimension-title">', mission_heading + 1)
    mission_section = body[mission_heading:next_after_mission]
    assert "not yet examined" in mission_section


def test_rate_opening_renders_bullets_and_line_breaks_as_html(
    client: TestClient, db_path: Path
) -> None:
    """A digest with leading-dash bullets and line breaks renders as `<ul>/<li>`
    or `<br>`, not literal text (Done When #4 of digest-latency-and-style)."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="stretch",
        digest="Evidence is mixed:\n- Autonomy is real.\n- Process is heavy.",
        assertion_count=1,
        computed_at=_NOW,
    )
    conn.close()

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert "<ul>" in body
    assert "<li>Autonomy is real.</li>" in body
    assert "<li>Process is heavy.</li>" in body
    assert "- Autonomy is real." not in body


def test_rate_opening_per_assertion_rendering_unchanged(client: TestClient, db_path: Path) -> None:
    """The per-assertion markup (target, fit chip, provenance chip, quote) stays the same."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="stretch",
        digest="Stretch digest.",
        assertion_count=1,
        computed_at=_NOW,
    )
    conn.close()

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert '<li class="fit-strong provenance-ratified">' in body
    assert '<span class="target">stretch</span>' in body
    assert '<span class="chip fit">Strong</span>' in body
    assert '<span class="chip provenance">ratified</span>' in body
    assert "<blockquote>verbatim source text</blockquote>" in body


def test_rate_opening_404_when_missing(client: TestClient) -> None:
    """A missing opening returns 404, not an error page."""
    response = client.get("/openings/no-such-opening/rate")
    assert response.status_code == 404


def test_static_css_is_reachable(client: TestClient) -> None:
    """The stylesheet mounted at `/static/app.css` is served."""
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
