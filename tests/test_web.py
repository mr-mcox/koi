"""Integration tests for the server-rendered HTML review surface."""

from __future__ import annotations

import contextlib
import json
import re
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screen.api.app import create_app
from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.research.actions import SearchAction, StopAction
from screen.research.batch import BatchEngine, opening_research_status
from screen.research.fakes import FakeBrowser
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.mappers import assertion_ruling_to_row
from screen.store.repo import (
    append_assertions,
    assertion_rulings_for_opening,
    assertions_for_opening,
    dimension_rulings_for_opening,
    get_opening,
    upsert_assertion_ruling,
    upsert_company,
    upsert_dimension_digest,
    upsert_dimension_ruling,
    upsert_opening,
)
from screen.types import (
    Assertion,
    AssertionRuling,
    Citation,
    Company,
    DimensionRuling,
    Fit,
    Opening,
    Provenance,
    Target,
)

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
    db_path: Path,
    *,
    company_id: str,
    opening_id: str,
    assertions: list[Assertion] | None = None,
    stage: str = "screening",
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
            stage=stage,  # type: ignore[arg-type]
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


def _boundary_glyph_positions(text: str) -> tuple[float, float, float]:
    """Return the rendered left position of the median marker plus the interval band's
    edges.
    Percentages are returned as fractions (0.0-1.0) in the order:
    median, low (range left edge), high (range right edge).
    """
    median_m = re.search(
        r'<span[^>]*class="[^"]*boundary-marker[^"]*boundary-median[^"]*"[^>]*style="[^"]*left:\s*([\d.]+)%',
        text,
    )
    range_m = re.search(
        r'<span[^>]*class="[^"]*boundary-range[^"]*"[^>]*style="[^"]*left:\s*([\d.]+)%;[^"]*right:\s*([\d.]+)%',
        text,
    )
    assert median_m is not None
    assert range_m is not None
    return (
        float(median_m.group(1)) / 100,
        float(range_m.group(1)) / 100,
        1 - float(range_m.group(2)) / 100,
    )


def _focus_snapshot_fields(body: str) -> dict[str, str]:
    """Extract the two hidden `focus_snapshot_*` fields the focused view echoes into
    every ruling-form, so a test can simulate what a real HTMX submit carries forward —
    the stable task set relies on the client round-tripping these."""
    fields = {}
    for name in ("focus_snapshot_assertion_ids", "focus_snapshot_dimension_targets"):
        match = re.search(rf'name="{name}" value="([^"]*)"', body)
        fields[name] = match.group(1) if match else ""
    return fields


def test_rate_opening_makes_no_live_digest_calls_when_cache_is_warm(db_path: Path) -> None:
    """A warm cache means the rating view never calls the digester — cold-cache
    generation happens post-pass, not on page view."""
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


def test_index_queue_reorders_after_assertion_ruling(client: TestClient, db_path: Path) -> None:
    """Submitting a ruling that raises an opening's standing re-sorts the HTML queue and
    the JSON queue in the same way."""
    config = load_scoring_config()
    poor_assertions = [
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
    _seed_opening(db_path, company_id="acme", opening_id="acme--ruled", assertions=poor_assertions)
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--unexamined")

    before = client.get("/")
    assert before.status_code == 200
    assert before.text.find("widgets--unexamined") < before.text.find("acme--ruled")

    conn = connect(db_path)
    for assertion in assertions_for_opening(conn, "acme--ruled"):
        response = client.post(
            f"/openings/acme--ruled/assertions/{assertion.id}/ruling",
            data={"fit": "Strong"},
        )
        assert response.status_code == 200
    conn.close()

    after = client.get("/")
    assert after.status_code == 200
    assert after.text.find("acme--ruled") < after.text.find("widgets--unexamined")

    json_response = client.get("/queue")
    assert json_response.status_code == 200
    json_ids = [item["opening_id"] for item in json_response.json()]
    assert json_ids == ["acme--ruled", "widgets--unexamined"]


def test_index_empty_queue_renders(client: TestClient) -> None:
    """An empty queue still returns a valid HTML document."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text


def test_index_queue_no_raw_floats_and_renders_boundary_glyph(
    client: TestClient, db_path: Path
) -> None:
    """The queue row replaces raw standing/reach/ceiling floats with the credible-
    interval boundary glyph (low/median/high on a fixed 0-1 `overall` axis)."""
    config = load_scoring_config()
    strong = [
        _assertion(slug, "Strong") for slug in (*config.dimension_weights, *config.constraints)
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=strong)
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    score_response = client.get("/queue")
    scores = score_response.json()
    score = next(item for item in scores if item["opening_id"] == "acme--eng")
    standing, reach, ceiling = score["standing"], score["reach"], score["ceiling"]
    assert f"{standing:.3f}" not in body
    assert f"{reach:.3f}" not in body
    assert f"{ceiling:.3f}" not in body
    assert "boundary-glyph" in body
    assert "sparkline" not in body
    assert "chip band" not in body
    for label in ("no path", "contender", "established", "capped", "wide open"):
        assert label not in body
    row_match = re.search(
        r"<li[^>]*>.*?acme--eng title.*?</li>",
        body,
        re.DOTALL,
    )
    assert row_match is not None
    median, range_left, range_right = _boundary_glyph_positions(row_match.group(0))
    assert range_left <= median <= range_right


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


def test_rate_opening_score_block_no_raw_floats_and_renders_boundary_glyph(
    client: TestClient, db_path: Path
) -> None:
    """The per-opening score block replaces raw floats with the credible-interval
    boundary glyph on the fixed 0-1 `overall` axis."""
    config = load_scoring_config()
    strong = [
        _assertion(slug, "Strong") for slug in (*config.dimension_weights, *config.constraints)
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=strong)
    response = client.get("/openings/acme--eng/rate")
    assert response.status_code == 200
    body = response.text
    score_response = client.get("/queue")
    score = next(item for item in score_response.json() if item["opening_id"] == "acme--eng")
    standing, reach, ceiling = score["standing"], score["reach"], score["ceiling"]
    assert f"{standing:.3f}" not in body
    assert f"{reach:.3f}" not in body
    assert f"{ceiling:.3f}" not in body
    assert "boundary-glyph" in body
    assert "sparkline" not in body
    assert "band-" not in body
    assert "chip band" not in body
    for label in ("no path", "contender", "established", "capped", "wide open"):
        assert label not in body

    median, range_left, range_right = _boundary_glyph_positions(body)
    assert range_left <= median <= range_right


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
    assert "fit-strong active" in stretch_section
    next_after_mission = body.find('<h3 class="dimension-title">', mission_heading + 1)
    mission_section = body[mission_heading:next_after_mission]
    assert "fit-mixed active" in mission_section


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
    or `<br>`, not literal text."""
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
    """The per-assertion markup (fit control, provenance glyph, quote) stays stable across
    dimension grouping; the target itself isn't repeated per assertion since the dimension
    heading above already names it."""
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

    assert "fit-strong active" in body
    assert 'title="ratified"' in body
    assert "<blockquote>verbatim source text</blockquote>" in body


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
    partial (not a full document) reflecting the new ruling — an HTMX partial swap,
    not a full-document GET."""
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
    assert "boundary-glyph" in response.text
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


def test_rate_opening_shows_dimension_ruling_control_per_group(
    client: TestClient, db_path: Path
) -> None:
    """Each dimension group offers a single-click 2D control to submit a `(fit,
    settledness)` pin."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.get("/openings/acme--eng/rate")

    body = response.text
    assert 'action="/openings/acme--eng/dimensions/stretch/ruling"' in body
    assert "dimension-ruling-pad" in body
    assert 'name="mean"' in body
    assert 'name="settledness"' in body


def test_rate_opening_shows_no_existing_dimension_ruling_by_default(
    client: TestClient, db_path: Path
) -> None:
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.get("/openings/acme--eng/rate")

    assert "dimension-ruling-pin" not in response.text


def test_rate_opening_shows_existing_dimension_ruling_distinctly(
    client: TestClient, db_path: Path
) -> None:
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    upsert_dimension_ruling(
        conn,
        DimensionRuling(
            opening_id="acme--eng", target="stretch", mean=0.5, settledness=0.8, created_at=_NOW
        ),
    )

    response = client.get("/openings/acme--eng/rate")

    assert "dimension-ruling-pin" in response.text


def test_rate_opening_shows_stale_border_when_pin_has_uncovered_assertions(
    client: TestClient, db_path: Path
) -> None:
    """A pin whose snapshot predates an assertion filed under its target renders the
    stale border class, distinct from a fresh pin."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    upsert_dimension_ruling(
        conn,
        DimensionRuling(
            opening_id="acme--eng",
            target="stretch",
            mean=0.5,
            settledness=0.8,
            created_at=_NOW,
            covered_assertion_ids=[],
        ),
    )

    response = client.get("/openings/acme--eng/rate")

    assert "dimension-ruling-pin-stale" in response.text


def test_rate_opening_omits_stale_border_when_pin_covers_every_assertion(
    client: TestClient, db_path: Path
) -> None:
    """A pin whose snapshot covers every assertion currently under its target is not
    stale and does not render the stale border class."""
    stretch = _assertion("stretch", "Strong")
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=[stretch])
    conn = connect(db_path)
    upsert_dimension_ruling(
        conn,
        DimensionRuling(
            opening_id="acme--eng",
            target="stretch",
            mean=0.5,
            settledness=0.8,
            created_at=_NOW,
            covered_assertion_ids=[stretch.id],
        ),
    )

    response = client.get("/openings/acme--eng/rate")

    assert "dimension-ruling-pin-stale" not in response.text


def test_submit_dimension_ruling_writes_and_swaps_partial(
    client: TestClient, db_path: Path
) -> None:
    """POSTing a dimension pin writes a `DimensionRuling` and returns the rating-content
    partial via HTMX swap."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.post(
        "/openings/acme--eng/dimensions/stretch/ruling",
        data={"mean": "0.5", "settledness": "0.8"},
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert 'id="rating-content"' in response.text
    assert "dimension-ruling-pin" in response.text

    conn = connect(db_path)
    rulings = dimension_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].target == "stretch"
    assert rulings[0].mean == 0.5
    assert rulings[0].settledness == 0.8


def test_submit_dimension_ruling_stamps_covered_assertion_ids(
    client: TestClient, db_path: Path
) -> None:
    """A pin snapshots the target's current assertion ids so later drift detection can
    tell exactly which assertions were and weren't seen."""
    stretch_assertions = [_assertion("stretch", "Strong"), _assertion("stretch", "Poor")]
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[*stretch_assertions, _assertion("internal_culture", "Strong")],
    )

    client.post(
        "/openings/acme--eng/dimensions/stretch/ruling",
        data={"mean": "0.5", "settledness": "0.8"},
    )

    conn = connect(db_path)
    rulings = dimension_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    stretch_ids = {a.id for a in stretch_assertions}
    assert set(rulings[0].covered_assertion_ids) == stretch_ids


def test_submit_dimension_ruling_replaces_prior_pin_for_same_target(
    client: TestClient, db_path: Path
) -> None:
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    client.post(
        "/openings/acme--eng/dimensions/stretch/ruling", data={"mean": "-0.5", "settledness": "0.2"}
    )
    client.post(
        "/openings/acme--eng/dimensions/stretch/ruling", data={"mean": "0.9", "settledness": "0.7"}
    )

    conn = connect(db_path)
    rulings = dimension_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].mean == 0.9
    assert rulings[0].settledness == 0.7


def test_submit_dimension_ruling_changes_standing(client: TestClient, db_path: Path) -> None:
    config = load_scoring_config()
    strong = [
        _assertion(slug, "Strong") for slug in (*config.dimension_weights, *config.constraints)
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=strong)

    before = client.get("/openings/acme--eng/rate")
    response = client.post(
        "/openings/acme--eng/dimensions/stretch/ruling",
        data={"mean": "-1.0", "settledness": "1.0"},
    )

    assert response.status_code == 200
    assert response.text != before.text


def test_submit_dimension_ruling_404_when_opening_missing(client: TestClient) -> None:
    response = client.post(
        "/openings/no-such-opening/dimensions/stretch/ruling",
        data={"mean": "0.5", "settledness": "0.8"},
    )
    assert response.status_code == 404


def test_submit_dimension_ruling_rejects_out_of_range_mean(
    client: TestClient, db_path: Path
) -> None:
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.post(
        "/openings/acme--eng/dimensions/stretch/ruling",
        data={"mean": "1.5", "settledness": "0.8"},
    )

    assert response.status_code == 422


def test_submit_dimension_ruling_rejects_out_of_range_settledness(
    client: TestClient, db_path: Path
) -> None:
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.post(
        "/openings/acme--eng/dimensions/stretch/ruling",
        data={"mean": "0.5", "settledness": "1.5"},
    )

    assert response.status_code == 422


def test_focus_opening_shows_only_budgeted_tasks(client: TestClient, db_path: Path) -> None:
    """`GET /openings/{id}/focus` renders only the highest-leverage unrated tasks, not
    every dimension/assertion."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[
            _assertion("stretch", "Strong"),
            _assertion("domain", "Strong"),
        ],
    )

    response = client.get("/openings/acme--eng/focus")

    assert response.status_code == 200
    body = response.text
    # stretch (weight 3, unexamined) should outrank domain (weight 1) for budget inclusion.
    assert '<h3 class="dimension-title">stretch</h3>' in body


def test_focus_opening_hides_fully_ruled_dimensions(client: TestClient, db_path: Path) -> None:
    """A dimension with a pin already in place has nothing left to rate and is excluded
    from the focused view."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion("stretch", "Strong")],
    )
    conn = connect(db_path)
    (stretch_id,) = [
        a.id for a in assertions_for_opening(conn, "acme--eng") if a.target == "stretch"
    ]
    upsert_dimension_ruling(
        conn,
        DimensionRuling(
            opening_id="acme--eng",
            target="stretch",
            mean=0.9,
            settledness=1.0,
            created_at=_NOW,
            covered_assertion_ids=[stretch_id],
        ),
    )

    response = client.get("/openings/acme--eng/focus")

    assert response.status_code == 200
    assert '<h3 class="dimension-title">stretch</h3>' not in response.text


def test_focus_opening_404_when_missing(client: TestClient) -> None:
    response = client.get("/openings/no-such-opening/focus")
    assert response.status_code == 404


def test_focus_opening_submission_stays_focused(client: TestClient, db_path: Path) -> None:
    """Submitting a ruling from the focused view keeps the swapped-in content focused,
    not the full unfiltered rating page — the same focused view, swapped via HTMX.
    Which targets are budgeted can legitimately shift after a rating changes the swing
    ranking — what must hold is that the swap stays under budget, not full."""
    all_targets = [
        "stretch",
        "schematic",
        "peer",
        "trajectory",
        "mission",
        "agentic",
        "compensation",
        "domain",
    ]
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[_assertion(target, "Strong") for target in all_targets],
    )
    focus_response = client.get("/openings/acme--eng/focus")
    budget = load_scoring_config().rating_task_budget
    focus_shown = [
        t for t in all_targets if f'<h3 class="dimension-title">{t}</h3>' in focus_response.text
    ]
    assert len(focus_shown) <= budget

    conn = connect(db_path)
    (assertion,) = [
        a for a in assertions_for_opening(conn, "acme--eng") if a.target in focus_shown
    ][:1]
    fields = _focus_snapshot_fields(focus_response.text)
    submit_response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling?focus=1",
        data={"fit": "Mixed", **fields},
    )
    assert submit_response.status_code == 200
    submit_shown = [
        t for t in all_targets if f'<h3 class="dimension-title">{t}</h3>' in submit_response.text
    ]
    assert len(submit_shown) <= budget


def test_focus_opening_dimension_ruling_keeps_dimension_visible(
    client: TestClient, db_path: Path
) -> None:
    """After submitting a dimension pin from the focused view, that dimension stays
    present in the swapped-in content — otherwise the task the operator just acted on
    vanishes mid-click, which reads as a bug even though the ranking is doing its job.
    Here `stretch` starts as the sole remaining task (its assertions are all ratified,
    so only the dimension pin is left); pinning it removes it from the candidate set
    entirely, but the just-completed group must still render — the just-acted-on task
    stays visible until the operator navigates away, not just while in budget.
    """
    assertions = [
        Assertion(
            target="stretch",
            fit="Strong",
            provenance="ratified",
            chunk="strong assertion",
            citations=[_CITATION],
            created_at=_NOW,
        ),
        Assertion(
            target="stretch",
            fit="Poor",
            provenance="ratified",
            chunk="poor assertion",
            citations=[_CITATION],
            created_at=_NOW,
        ),
        Assertion(
            target="stretch",
            fit="Mixed",
            provenance="ratified",
            chunk="mixed assertion",
            citations=[_CITATION],
            created_at=_NOW,
        ),
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=assertions)
    conn = connect(db_path)
    for a in assertions:
        upsert_assertion_ruling(
            conn,
            AssertionRuling(
                id=str(uuid4()), assertion_id=a.id, fit=cast(Fit, a.fit), created_at=_NOW
            ),
        )

    before = client.get("/openings/acme--eng/focus")
    assert before.status_code == 200
    assert '<h3 class="dimension-title">stretch</h3>' in before.text

    fields = _focus_snapshot_fields(before.text)
    after = client.post(
        "/openings/acme--eng/dimensions/stretch/ruling?focus=1",
        data={"mean": "0.5", "settledness": "0.8", **fields},
    )
    assert after.status_code == 200
    assert '<h3 class="dimension-title">stretch</h3>' in after.text


def test_focus_opening_stable_task_set_survives_multiple_submissions(
    client: TestClient, db_path: Path
) -> None:
    """Completing task B must not make task A disappear (operator feedback): the
    focused screen's task set is fixed at the initial GET and echoed back via hidden
    `focus_snapshot_*` fields on every submit, not recomputed after each one — so both
    A and B stay visible for the whole session, and no new task not shown on the
    initial GET appears either."""
    a_target_assertion = Assertion(
        target="stretch",
        fit="Strong",
        provenance="model_proposed",
        chunk="stretch assertion",
        citations=[_CITATION],
        created_at=_NOW,
    )
    b_target_assertion = Assertion(
        target="domain",
        fit="Strong",
        provenance="model_proposed",
        chunk="domain assertion",
        citations=[_CITATION],
        created_at=_NOW,
    )
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[a_target_assertion, b_target_assertion],
    )

    initial = client.get("/openings/acme--eng/focus")
    assert initial.status_code == 200
    assert '<h3 class="dimension-title">stretch</h3>' in initial.text
    assert '<h3 class="dimension-title">domain</h3>' in initial.text
    fields = _focus_snapshot_fields(initial.text)

    conn = connect(db_path)
    (a_id,) = [a.id for a in assertions_for_opening(conn, "acme--eng") if a.target == "stretch"]
    (b_id,) = [a.id for a in assertions_for_opening(conn, "acme--eng") if a.target == "domain"]

    after_a = client.post(
        f"/openings/acme--eng/assertions/{a_id}/ruling?focus=1",
        data={"fit": "Mixed", **fields},
    )
    assert after_a.status_code == 200
    assert '<h3 class="dimension-title">stretch</h3>' in after_a.text
    assert '<h3 class="dimension-title">domain</h3>' in after_a.text

    after_b = client.post(
        f"/openings/acme--eng/assertions/{b_id}/ruling?focus=1",
        data={"fit": "Mixed", **fields},
    )
    assert after_b.status_code == 200
    assert '<h3 class="dimension-title">stretch</h3>' in after_b.text
    assert '<h3 class="dimension-title">domain</h3>' in after_b.text


def test_focus_view_shows_next_opening_link(client: TestClient, db_path: Path) -> None:
    """The focused view for an opening includes a link to the next opening in leverage
    order, so the operator can continue the session without returning to the queue."""
    first = Assertion(
        target="stretch",
        fit="Strong",
        provenance="model_proposed",
        chunk="chunk",
        citations=[_CITATION],
        created_at=_NOW,
    )
    second = Assertion(
        target="stretch",
        fit="Strong",
        provenance="model_proposed",
        chunk="chunk",
        citations=[_CITATION],
        created_at=_NOW,
    )
    _seed_opening(db_path, company_id="first", opening_id="first--eng", assertions=[first])
    _seed_opening(db_path, company_id="second", opening_id="second--eng", assertions=[second])

    response = client.get("/openings/first--eng/focus")

    assert response.status_code == 200
    assert "/openings/second--eng/focus" in response.text
    assert "Next opening" in response.text


def test_focus_view_last_opening_shows_back_to_queue(client: TestClient, db_path: Path) -> None:
    """The focused view for the last opening shows a link back to the queue instead of a
    disabled next link."""
    _seed_opening(db_path, company_id="only", opening_id="only--eng", assertions=[])

    response = client.get("/openings/only--eng/focus")

    assert response.status_code == 200
    assert "Back to queue" in response.text


def test_focus_opening_assertion_only_task_hides_digest_and_dimension_control(
    client: TestClient, db_path: Path
) -> None:
    """When the highest-ranked candidate for a target is an assertion-ruling task, not
    the whole-dimension pin, the focused view shows that assertion without the digest or
    dimension-ruling pad — those belong to the bigger, unselected task. Fixture found by
    search: `stretch`'s only budgeted candidate is its lone assertion, not a dimension
    task, under the fixed scoring seed."""
    fixture = [
        ("stretch", "Poor", "model_proposed"),
        ("schematic", "Poor", "ratified"),
        ("schematic", "Strong", "precedent_matched"),
        ("schematic", "Mixed", "ratified"),
        ("peer", "Strong", "model_proposed"),
        ("peer", "Strong", "ratified"),
        ("trajectory", "Mixed", "ratified"),
        ("trajectory", "Mixed", "ratified"),
        ("mission", "Strong", "precedent_matched"),
        ("mission", "Strong", "precedent_matched"),
        ("mission", "Poor", "model_proposed"),
        ("agentic", "Mixed", "precedent_matched"),
        ("agentic", "Mixed", "precedent_matched"),
        ("agentic", "Strong", "model_proposed"),
        ("compensation", "Poor", "model_proposed"),
        ("compensation", "Poor", "model_proposed"),
        ("domain", "Poor", "model_proposed"),
        ("domain", "Strong", "ratified"),
        ("domain", "Mixed", "ratified"),
        ("location", "Mixed", "precedent_matched"),
        ("location", "Strong", "ratified"),
        ("internal_culture", "Strong", "precedent_matched"),
        ("internal_culture", "Mixed", "precedent_matched"),
        ("internal_culture", "Poor", "precedent_matched"),
        ("extractive_business", "Strong", "ratified"),
        ("extractive_business", "Poor", "precedent_matched"),
        ("extractive_business", "Mixed", "precedent_matched"),
        ("extractive_business", "Strong", "ratified"),
    ]
    assertions = [
        Assertion(
            target=cast(Target, target),
            fit=cast(Fit, fit),
            provenance=cast(Provenance, provenance),
            chunk=f"{target}-{provenance}-{fit}",
            citations=[_CITATION],
            created_at=_NOW,
        )
        for target, fit, provenance in fixture
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=assertions)
    response = client.get("/openings/acme--eng/focus")
    assert response.status_code == 200
    body = response.text
    assert '<h3 class="dimension-title">stretch</h3>' in body
    stretch_section = body[body.index('<h3 class="dimension-title">stretch</h3>') :]
    stretch_section = stretch_section[: stretch_section.find("</section>")]
    assert "digest" not in stretch_section.lower()
    assert "dimension-ruling-pad" not in stretch_section


def test_focus_opening_context_assertions_under_dimension_task_are_collapsible(
    client: TestClient, db_path: Path
) -> None:
    """When the budgeted task for a target is the whole-dimension pin, assertions
    underneath are shown collapsed by default (compact, not full interactive cards) but
    remain reachable — expand to correct one if it's the reason the dimension pin feels
    wrong (operator principle: always able to dig into what's lower in the hierarchy).
    Here `stretch` has all three assertions already ruled, so the only remaining budgeted
    task is the dimension pin; the assertions must still carry a `ruling-form` (reachable),
    just collapsed inside a `<details>` disclosure, not open by default."""
    assertions = [
        Assertion(
            target="stretch",
            fit="Strong",
            provenance="ratified",
            chunk="strong assertion",
            citations=[_CITATION],
            created_at=_NOW,
        ),
        Assertion(
            target="stretch",
            fit="Poor",
            provenance="ratified",
            chunk="poor assertion",
            citations=[_CITATION],
            created_at=_NOW,
        ),
        Assertion(
            target="stretch",
            fit="Mixed",
            provenance="ratified",
            chunk="mixed assertion",
            citations=[_CITATION],
            created_at=_NOW,
        ),
    ]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=assertions)
    conn = connect(db_path)
    for assertion, fit in zip(assertions, ["Strong", "Poor", "Mixed"], strict=True):
        upsert_assertion_ruling(
            conn,
            AssertionRuling(
                id=str(uuid4()),
                assertion_id=assertion.id,
                fit=cast(Fit, fit),
                created_at=_NOW,
            ),
        )

    response = client.get("/openings/acme--eng/focus")
    assert response.status_code == 200
    body = response.text
    assert "dimension-ruling-pad" in body
    assert "strong assertion" in body
    assert "poor assertion" in body
    assert "mixed assertion" in body
    stretch_section = body[body.index('<h3 class="dimension-title">stretch</h3>') :]
    stretch_section = stretch_section[: stretch_section.find("</section>")]
    # reachable — the fit-ruling form is present so an assertion can be corrected
    assert stretch_section.count('class="ruling-form"') == 3
    # but collapsed by default, not one interactive card per assertion up front
    assert stretch_section.count("<details") == 3
    assert "<details open" not in stretch_section
    # collapsed summary carries the provenance glyph, a compact fit indicator, and the
    # truncated snippet — not the full assertion text or a verbose fit label
    first_summary = stretch_section[stretch_section.index("<summary>") :]
    first_summary = first_summary[: first_summary.index("</summary>")]
    assert "provenance-glyph" in first_summary
    assert 'class="fit-indicator"' in first_summary
    assert "fit-static" not in first_summary


def test_index_renders_contested_review_link(client: TestClient, db_path: Path) -> None:
    """The queue page exposes a manual-testing entrance to the new
    crossing-probability ordering, without displaying the numeric value."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.get("/")

    assert response.status_code == 200
    assert "Start contested review" in response.text
    assert 'href="/contested"' in response.text


def test_contested_redirect_to_highest_crossing_probability_opening(
    client: TestClient, db_path: Path
) -> None:
    """`GET /contested` redirects to the opening with the highest crossing probability,
    which is the highest-standing opening under deterministic seeding."""
    config = load_scoring_config()
    targets = (*config.dimension_weights, *config.constraints)
    for i in range(config.top_k):
        poor_target = targets[0] if i > 0 else None
        assertions = [
            _assertion(slug, "Poor" if slug == poor_target else "Strong") for slug in targets
        ]
        _seed_opening(db_path, company_id=f"c{i}", opening_id=f"c{i}--eng", assertions=assertions)

    response = client.get("/contested", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/openings/c0--eng/contested"


def test_contested_redirect_falls_back_to_queue_when_fewer_than_top_k(
    client: TestClient, db_path: Path
) -> None:
    """With fewer than `top_k` openings there is no K-th boundary, so the session
    entry point falls back to the queue rather than defaulting an ordering."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.get("/contested", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"


def test_index_queue_hides_boundary_tick_when_fewer_than_top_k(
    client: TestClient, db_path: Path
) -> None:
    """With fewer than `top_k` scored openings there is no K-th opening, so the queue
    row's glyph has no boundary tick and no crossing-probability tooltip — the boundary
    does not exist yet."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "boundary-glyph" in body
    assert "boundary-tick" not in body
    assert "chance of crossing the boundary" not in body


def test_index_queue_shows_boundary_tick_when_at_least_top_k(
    client: TestClient, db_path: Path
) -> None:
    """With at least `top_k` scored openings the K-th opening exists, so every row's
    glyph shows a boundary tick and a crossing-probability tooltip."""
    config = load_scoring_config()
    targets = (*config.dimension_weights, *config.constraints)
    for i in range(config.top_k):
        _seed_opening(
            db_path,
            company_id=f"c{i}",
            opening_id=f"c{i}--eng",
            assertions=[_assertion(slug, "Strong") for slug in targets],
        )

    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "boundary-tick" in body
    assert "chance of crossing the boundary" in body


def test_rate_opening_score_block_shares_boundary_glyph_macro_with_queue(
    client: TestClient, db_path: Path
) -> None:
    """The per-opening score block renders the same marks (interval band, median dot,
    boundary tick) as the queue row, via the shared `boundary_glyph` macro."""
    config = load_scoring_config()
    targets = (*config.dimension_weights, *config.constraints)
    for i in range(config.top_k):
        _seed_opening(
            db_path,
            company_id=f"c{i}",
            opening_id=f"c{i}--eng",
            assertions=[_assertion(slug, "Strong") for slug in targets],
        )

    response = client.get("/openings/c0--eng/rate")

    assert response.status_code == 200
    body = response.text
    assert "boundary-glyph" in body
    for mark in ("boundary-range", "boundary-median", "boundary-tick"):
        assert mark in body


def test_contested_per_opening_shows_next_link(client: TestClient, db_path: Path) -> None:
    """A contested review session chains through openings ordered by the signal, without
    rendering the probability value. It reuses the focused per-opening UI so the operator
    sees only the high-leverage tasks worth rating."""
    config = load_scoring_config()
    targets = (*config.dimension_weights, *config.constraints)
    for i in range(config.top_k):
        poor_target = targets[0] if i > 0 else None
        assertions = [
            _assertion(slug, "Poor" if slug == poor_target else "Strong") for slug in targets
        ]
        _seed_opening(db_path, company_id=f"c{i}", opening_id=f"c{i}--eng", assertions=assertions)

    response = client.get("/openings/c0--eng/contested")

    assert response.status_code == 200
    assert "Next contested opening" in response.text
    assert 'href="/openings/' in response.text
    assert '/contested"' in response.text
    # Focused UI: the page carries the stable-task-set snapshot and submits via focus=1.
    assert 'name="focus_snapshot_assertion_ids"' in response.text
    assert 'name="focus_snapshot_dimension_targets"' in response.text
    assert '?focus=1"' in response.text


def test_contested_per_opening_last_shows_back_to_queue(client: TestClient, db_path: Path) -> None:
    """The last opening in the contested ordering offers a link back to the queue."""
    config = load_scoring_config()
    targets = (*config.dimension_weights, *config.constraints)
    for i in range(config.top_k):
        poor_target = targets[0] if i > 0 else None
        assertions = [
            _assertion(slug, "Poor" if slug == poor_target else "Strong") for slug in targets
        ]
        _seed_opening(db_path, company_id=f"c{i}", opening_id=f"c{i}--eng", assertions=assertions)

    response = client.get(f"/openings/c{config.top_k - 1}--eng/contested")

    assert response.status_code == 200
    assert "Back to queue" in response.text


def test_contested_session_skips_openings_with_no_rating_tasks(
    client: TestClient, db_path: Path
) -> None:
    """A contested opening with no remaining rating tasks has nothing for the operator
    to evaluate there — the uncertainty is inherent in the opportunity, not actionable
    by rating — so the session skips it even if its crossing probability is high."""
    config = load_scoring_config()
    targets = (*config.dimension_weights, *config.constraints)

    def _strong() -> list[Assertion]:
        return [_assertion(slug, "Strong") for slug in targets]

    # Fully ruled/pinned: highest standing but no rating tasks left.
    _seed_opening(db_path, company_id="done", opening_id="done--eng", assertions=_strong())
    conn = connect(db_path)
    for a in assertions_for_opening(conn, "done--eng"):
        upsert_assertion_ruling(
            conn,
            AssertionRuling(id=str(uuid4()), assertion_id=a.id, fit="Strong", created_at=_NOW),
        )
    for target in targets:
        covered_ids = [
            a.id for a in assertions_for_opening(conn, "done--eng") if a.target == target
        ]
        upsert_dimension_ruling(
            conn,
            DimensionRuling(
                opening_id="done--eng",
                target=target,
                mean=1.0,
                settledness=1.0,
                created_at=_NOW,
                covered_assertion_ids=covered_ids,
            ),
        )
    conn.close()

    # Same evidence but unruled: second-highest standing and has rating tasks.
    _seed_opening(db_path, company_id="active", opening_id="active--eng", assertions=_strong())

    # Fill the rest of the queue so the boundary exists.
    for i in range(config.top_k - 2):
        poor = [_assertion(slug, "Poor") for slug in targets]
        _seed_opening(db_path, company_id=f"f{i}", opening_id=f"f{i}--eng", assertions=poor)

    response = client.get("/contested", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/openings/active--eng/contested"


_LIVE_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _seed_research_trace(data_root: Path, opening_id: str) -> None:
    """Write a minimal research trace so the batch engine can resume the opening."""
    trace_path = data_root / "research_traces" / f"tx-{opening_id}.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://example.com/{opening_id}"
    trace_path.write_text(
        json.dumps(
            {
                "ts": _LIVE_NOW.isoformat(),
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {
                    "results": [{"url": url, "raw_content": f"Posting for {opening_id}."}]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_live_opening(db_path: Path, opening_id: str, budget: int = 5) -> None:
    conn = connect(db_path)
    company_id = opening_id.split("--", maxsplit=1)[0]
    upsert_company(conn, Company(id=company_id, name=f"{company_id} Inc", created_at=_LIVE_NOW))
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title=f"{opening_id} title",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            research_turns_budget=budget,
            created_at=_LIVE_NOW,
        ),
    )
    conn.close()
    _seed_research_trace(db_path.parent, opening_id)


@contextlib.contextmanager
def _live_server(app: FastAPI) -> Iterator[str]:
    """Run `app` in a uvicorn thread and yield its base URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=1)
        raise RuntimeError("live server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=2)


class PausablePlanner:
    """Fake planner that blocks on the first `plan()` call until `gate` is set,
    then returns one `SearchAction` and stops on subsequent calls."""

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self._called = 0

    def plan(self, _state: object) -> list:
        self._called += 1
        if self._called == 1:
            self._gate.wait()
            return [SearchAction(query="paused query")]
        return [StopAction(reason="done")]


def _pausable_engine(gate: threading.Event) -> BatchEngine:
    """Engine whose first-turn planner blocks on `gate`, then spends one fake turn."""
    shared_planner = PausablePlanner(gate)
    return BatchEngine(
        planner_factory=lambda: shared_planner,
        browser_factory=lambda: FakeBrowser(search_fixtures={"paused query": []}),
        extractor_factory=lambda: FakeExtractor([[_assertion("stretch", "Strong")]]),
        digester_factory=lambda: FakeDigester(["Synthetic digest."]),
    )


def test_batch_start_returns_before_turn_is_spent(db_path: Path) -> None:
    """POST /batch schedules the work in a background task and returns immediately,
    before the slow planner even finishes its first `plan()` call."""
    _seed_live_opening(db_path, "acme--eng")
    app = create_app(db_path, digester=FakeDigester(["Synthetic digest."]))
    gate = threading.Event()
    app.state.batch_engine = _pausable_engine(gate)

    with _live_server(app) as base, httpx.Client() as client:
        t0 = time.time()
        response = client.post(f"{base}/batch", data={"batch_size": "3"})
        t1 = time.time()
        assert response.status_code == 200, response.text
        assert "Batch running" in response.text
        # The response must land before the gate is released.
        assert t1 - t0 < 0.5

        # Poll the status endpoint while the batch is still blocked; the current
        # opening id may take a moment to appear as the background thread starts.
        current_opening_id: str | None = None
        for _ in range(50):
            status = client.get(f"{base}/batch-status")
            assert status.status_code == 200
            if "Batch running" in status.text:
                if "working on acme--eng" in status.text:
                    current_opening_id = "acme--eng"
                    break
            time.sleep(0.05)
        else:
            raise AssertionError("batch did not show running status")
        assert current_opening_id == "acme--eng"

        # Now let the background task finish its first (and only) turn.
        gate.set()
        for _ in range(50):
            status = client.get(f"{base}/batch-status")
            if "No batch running" in status.text:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("batch never finished")
        assert "Batch running" not in status.text

        # One turn was actually spent.
        conn = connect(db_path)
        opening = get_opening(conn, "acme--eng")
        assert opening is not None
        used, budget = opening_research_status(db_path.parent, opening)
        conn.close()
        assert (used, budget) == (2, 5)


def test_second_batch_start_is_rejected_while_one_is_running(db_path: Path) -> None:
    """Two rapid POST /batch requests only run one batch; the second gets a clear error."""
    _seed_live_opening(db_path, "acme--eng")
    _seed_live_opening(db_path, "widgets--eng")
    app = create_app(db_path, digester=FakeDigester(["Synthetic digest."]))
    gate = threading.Event()
    app.state.batch_engine = _pausable_engine(gate)

    with _live_server(app) as base, httpx.Client() as client:
        first = client.post(f"{base}/batch", data={"batch_size": "3"})
        assert first.status_code == 200
        assert "Batch running" in first.text

        second = client.post(f"{base}/batch", data={"batch_size": "3"})
        assert second.status_code == 200
        assert "already running" in second.text

        gate.set()


def test_queue_shows_research_turns_used_and_budget(client: TestClient, db_path: Path) -> None:
    """Each queue item renders the same turns-used/budget line the retired
    `research-status` CLI printed."""
    _seed_live_opening(db_path, "acme--eng", budget=5)
    response = client.get("/")
    assert response.status_code == 200
    assert "1/5" in response.text  # one tavily_extract turn in the seeded trace


def test_batch_start_form_validates_batch_size(client: TestClient) -> None:
    """The batch start form rejects non-positive batch sizes."""
    response = client.post("/batch", data={"batch_size": "0"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Opening lifecycle stage
# ---------------------------------------------------------------------------


def test_queue_excludes_openings_not_in_screening_stage(client: TestClient, db_path: Path) -> None:
    """The ranked HTML queue and the JSON `/queue` only ever list `screening`-stage
    openings — `pursuing`/`applied`/`closed` openings leave the live queue."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--screening")
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--pursuing", stage="pursuing")
    _seed_opening(db_path, company_id="globex", opening_id="globex--applied", stage="applied")
    _seed_opening(db_path, company_id="initech", opening_id="initech--closed", stage="closed")

    html = client.get("/")
    json_response = client.get("/queue")

    assert html.status_code == 200
    assert "acme--screening" in html.text
    for excluded in ("widgets--pursuing", "globex--applied", "initech--closed"):
        assert excluded not in html.text

    json_ids = [item["opening_id"] for item in json_response.json()]
    assert json_ids == ["acme--screening"]


def test_moving_opening_out_of_screening_drops_it_from_boundary_computation(
    client: TestClient, db_path: Path
) -> None:
    """A de-queued opening never anchors the `top_k` boundary — moving the K-th-ranked
    opening out of `screening` shifts the boundary to the new K-th opening."""
    config = load_scoring_config()
    targets = (*config.dimension_weights, *config.constraints)
    for i in range(config.top_k + 1):
        _seed_opening(
            db_path,
            company_id=f"c{i}",
            opening_id=f"c{i}--eng",
            assertions=[_assertion(slug, "Strong") for slug in targets],
        )

    before = client.get("/queue").json()
    assert len(before) == config.top_k + 1

    conn = connect(db_path)
    top_opening = get_opening(conn, before[0]["opening_id"])
    assert top_opening is not None
    upsert_opening(conn, top_opening.model_copy(update={"stage": "applied"}))
    conn.close()

    after = client.get("/queue").json()
    assert len(after) == config.top_k
    assert before[0]["opening_id"] not in [item["opening_id"] for item in after]


def test_submit_stage_change_updates_opening_and_redirects_to_queue(
    client: TestClient, db_path: Path
) -> None:
    """Posting a new stage for an opening persists it and leaves the rating view (the
    operator's request: a lightweight marker, not a full application tracker)."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.post(
        "/openings/acme--eng/stage", data={"stage": "pursuing"}, follow_redirects=False
    )

    assert response.status_code in (302, 303)
    conn = connect(db_path)
    opening = get_opening(conn, "acme--eng")
    assert opening is not None
    assert opening.stage == "pursuing"


def test_submit_stage_change_rejects_unknown_stage(client: TestClient, db_path: Path) -> None:
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.post("/openings/acme--eng/stage", data={"stage": "ghosted"})

    assert response.status_code == 422


def test_submit_stage_change_404s_for_unknown_opening(client: TestClient) -> None:
    response = client.post("/openings/does-not-exist/stage", data={"stage": "applied"})
    assert response.status_code == 404


def test_rating_view_shows_stage_controls(client: TestClient, db_path: Path) -> None:
    """The rating view exposes a way to change an opening's stage (F13: same page the
    operator already reviews the opening from)."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    assert "/openings/acme--eng/stage" in response.text
    for stage in ("screening", "pursuing", "applied", "closed"):
        assert stage in response.text


def test_archive_view_lists_openings_by_stage(client: TestClient, db_path: Path) -> None:
    """`/archive` lists every non-`screening` opening, filterable by stage, each linking
    back to its existing rating view for recall (F8/F15)."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--screening")
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--pursuing", stage="pursuing")
    _seed_opening(db_path, company_id="globex", opening_id="globex--applied", stage="applied")
    _seed_opening(db_path, company_id="initech", opening_id="initech--closed", stage="closed")

    response = client.get("/archive")

    assert response.status_code == 200
    body = response.text
    assert "acme--screening" not in body
    assert "widgets--pursuing" in body
    assert "globex--applied" in body
    assert "initech--closed" in body
    assert "/openings/widgets--pursuing/rate" in body


def test_archive_view_filters_to_one_stage_via_query_param(
    client: TestClient, db_path: Path
) -> None:
    _seed_opening(db_path, company_id="widgets", opening_id="widgets--pursuing", stage="pursuing")
    _seed_opening(db_path, company_id="globex", opening_id="globex--applied", stage="applied")

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
