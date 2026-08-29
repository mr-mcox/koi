"""Integration tests for the server-rendered HTML review surface."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from screen.api.app import create_app
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.mappers import assertion_ruling_to_row
from screen.store.repo import (
    append_assertions,
    assertion_rulings_for_opening,
    upsert_company,
    upsert_opening,
)
from screen.types import Assertion, AssertionRuling, Citation, Company, Fit, Opening, Target

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


def _assertion(target: Target, fit: Fit) -> Assertion:
    return Assertion(
        target=target,
        fit=fit,
        provenance="ratified",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )


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


def test_rate_opening_404_when_missing(client: TestClient) -> None:
    """A missing opening returns 404, not an error page."""
    response = client.get("/openings/no-such-opening/rate")
    assert response.status_code == 404


def test_rate_opening_renders_citation_link(client: TestClient, db_path: Path) -> None:
    """Each assertion's citation renders as a clickable link to its `url`."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.get("/openings/acme--eng/rate")

    body = response.text
    assert f'href="{_CITATION.url}"' in body
    assert _CITATION.host in body


def test_rate_opening_shows_model_proposed_provenance(client: TestClient, db_path: Path) -> None:
    """An assertion with no recorded ruling shows its provenance as a compact glyph
    and renders the fit control active at the model's proposed value."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.get("/openings/acme--eng/rate")

    body = response.text
    assert "provenance-glyph" in body
    assert 'title="ratified"' in body
    assert 'value="Strong"' in body
    assert "fit-strong active" in body


def test_rate_opening_shows_existing_ruling_in_fit_control(
    client: TestClient, db_path: Path
) -> None:
    """An `AssertionRuling` already recorded for an assertion makes the control's
    active segment reflect the operator's value, not the original proposal."""
    assertion = _assertion("stretch", "Mixed")
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[assertion],
    )
    conn = connect(db_path)
    ruling = AssertionRuling(assertion_id=assertion.id, fit="Strong", created_at=_NOW)
    conn.execute(
        """INSERT INTO assertion_rulings (id, assertion_id, fit, created_at)
           VALUES (:id, :assertion_id, :fit, :created_at)""",
        assertion_ruling_to_row(ruling),
    )
    conn.commit()

    response = client.get("/openings/acme--eng/rate")

    body = response.text
    assert "fit-strong active" in body
    assert 'value="Strong"' in body


def test_rate_opening_ruling_flips_provenance_glyph_to_ratified(
    client: TestClient, db_path: Path
) -> None:
    """Once an operator ruling exists for an assertion, the glyph shows `ratified`
    (the operator's own review), not the model's original provenance — the glyph
    signals "has this been reviewed," not the assertion's frozen history."""
    assertion = Assertion(
        target="internal_culture",
        fit="Strong",
        provenance="model_proposed",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[assertion],
    )
    conn = connect(db_path)
    ruling = AssertionRuling(assertion_id=assertion.id, fit="Mixed", created_at=_NOW)
    conn.execute(
        """INSERT INTO assertion_rulings (id, assertion_id, fit, created_at)
           VALUES (:id, :assertion_id, :fit, :created_at)""",
        assertion_ruling_to_row(ruling),
    )
    conn.commit()

    response = client.get("/openings/acme--eng/rate")

    body = response.text
    assert 'title="ratified"' in body
    assert "provenance-model_proposed" not in body


def test_static_css_is_reachable(client: TestClient) -> None:
    """The stylesheet mounted at `/static/app.css` is served."""
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_static_htmx_is_reachable(client: TestClient) -> None:
    """Vendored htmx (no CDN/SRI drift risk) is served from the same static mount —
    every ruling submission on the rating page depends on this loading."""
    response = client.get("/static/htmx.min.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript") or response.headers[
        "content-type"
    ].startswith("application/javascript")


def test_submit_ruling_writes_and_swaps_partial(client: TestClient, db_path: Path) -> None:
    """POSTing an override writes an `AssertionRuling` and returns the rating content
    partial (not a full document) reflecting the new ruling (Done When: HTMX partial
    swap, not a full-document GET)."""
    assertion = _assertion("stretch", "Mixed")
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[assertion],
    )

    response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Strong"}
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert 'id="rating-content"' in response.text
    assert "fit-strong active" in response.text
    assert 'value="Strong"' in response.text

    conn = connect(db_path)
    rulings = assertion_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].assertion_id == assertion.id
    assert rulings[0].fit == "Strong"


def test_submit_ruling_confirming_current_value_still_ratifies(
    client: TestClient, db_path: Path
) -> None:
    """Clicking the already-active segment is an explicit confirm, not a no-op —
    it still records a ruling and flips the glyph to `ratified`."""
    assertion = Assertion(
        target="stretch",
        fit="Strong",
        provenance="model_proposed",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[assertion],
    )

    response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Strong"}
    )

    assert response.status_code == 200
    assert 'title="ratified"' in response.text

    conn = connect(db_path)
    rulings = assertion_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].fit == "Strong"


def test_submit_ruling_changes_the_score(client: TestClient, db_path: Path) -> None:
    """Submitting a ruling changes the rendered standing when it flips a target's fit."""
    config = load_scoring_config()
    strong = [
        _assertion(slug, "Strong") for slug in (*config.dimension_weights, *config.constraints)
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=strong)
    stretch_assertion = next(a for a in strong if a.target == "stretch")

    before = client.get("/openings/acme--eng/rate")
    response = client.post(
        f"/openings/acme--eng/assertions/{stretch_assertion.id}/ruling", data={"fit": "Poor"}
    )

    assert response.status_code == 200
    assert "standing" in response.text
    assert response.text != before.text


def test_submit_ruling_replaces_prior_ruling_for_same_assertion(
    client: TestClient, db_path: Path
) -> None:
    """Re-submitting an override for the same assertion replaces the stored ruling."""
    assertion = _assertion("stretch", "Mixed")
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[assertion],
    )

    client.post(f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Strong"})
    client.post(f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Poor"})

    conn = connect(db_path)
    rulings = assertion_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].fit == "Poor"


def test_submit_ruling_404_when_opening_missing(client: TestClient) -> None:
    response = client.post(
        "/openings/no-such-opening/assertions/no-such-assertion/ruling", data={"fit": "Strong"}
    )
    assert response.status_code == 404


def test_submit_ruling_rejects_invalid_fit(client: TestClient, db_path: Path) -> None:
    assertion = _assertion("stretch", "Mixed")
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[assertion],
    )

    response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Excellent"}
    )

    assert response.status_code == 422
