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

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screen.api.app import create_app
from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.intake.research_trace_replay import replay_research_trace
from screen.research.actions import SearchAction, StopAction
from screen.research.batch import BatchEngine, RunDispatchDeps, research_trace_path_for
from screen.research.fakes import FakeBrowser
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.mappers import assertion_ruling_to_row
from screen.store.repo import (
    append_assertions,
    append_comparison,
    assertion_rulings_for_opening,
    assertions_for_opening,
    get_opening,
    upsert_company,
    upsert_dimension_digest,
    upsert_opening,
)
from screen.types import (
    Assertion,
    AssertionRuling,
    Citation,
    Company,
    Comparison,
    Fit,
    Opening,
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
    strong = [_assertion(slug, "Strong") for slug in (*config.dimension_weights,)]
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
        for slug in (*config.dimension_weights,)
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


def test_index_queue_reorders_after_comparison(client: TestClient, db_path: Path) -> None:
    """A stored comparison must reach the same `_ranked_pool` the HTML queue and JSON
    `/queue` both render from — the wiring `pool_for_screening`'s comparison args
    depend on (`comparisons_by_target`/`companies_by_opening`), not just the pure fit."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )
    _seed_opening(
        db_path,
        company_id="widgets",
        opening_id="widgets--b",
        assertions=[_assertion("stretch", "Strong")],
    )

    before = client.get("/")
    assert before.status_code == 200

    conn = connect(db_path)
    for _ in range(3):
        append_comparison(
            conn,
            Comparison(
                opening_a_id="widgets--b",
                opening_b_id="acme--a",
                target="stretch",
                outcome="a",
                predicted_a_beats_b=0.5,
                created_at=_NOW,
            ),
        )
    conn.close()

    after = client.get("/")
    assert after.status_code == 200
    assert after.text.find("widgets--b") < after.text.find("acme--a")

    json_response = client.get("/queue")
    assert json_response.status_code == 200
    json_ids = [item["opening_id"] for item in json_response.json()]
    assert json_ids == ["widgets--b", "acme--a"]


def test_compare_page_reachable_from_queue_and_submits_winner(
    client: TestClient, db_path: Path
) -> None:
    """The operator can pick any two openings and a scoring dimension, submit that A
    beats B, and the queue immediately reorders through the same comparison-fitted
    pool. The stored comparison row carries the pre-comparison probability computed
    from assertion priors."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )
    _seed_opening(
        db_path,
        company_id="widgets",
        opening_id="widgets--b",
        assertions=[_assertion("stretch", "Strong")],
    )

    queue = client.get("/")
    assert queue.status_code == 200
    assert 'href="/compare"' in queue.text

    get_response = client.get("/compare")
    assert get_response.status_code == 200
    assert "stretch" in get_response.text
    assert 'class="compare-column-title"' not in get_response.text

    post_response = client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "stretch",
            "outcome": "a",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    assert post_response.headers["location"] == "/compare"

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT opening_a_id, opening_b_id, target, outcome, predicted_a_beats_b FROM comparisons"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert dict(rows[0]) == {
        "opening_a_id": "acme--a",
        "opening_b_id": "widgets--b",
        "target": "stretch",
        "outcome": "a",
        "predicted_a_beats_b": pytest.approx(0.5),
    }

    after = client.get("/")
    assert after.status_code == 200
    assert after.text.find("acme--a") < after.text.find("widgets--b")

    json_response = client.get("/queue")
    assert json_response.status_code == 200
    assert [item["opening_id"] for item in json_response.json()] == ["acme--a", "widgets--b"]


def test_compare_page_previews_target_digests(client: TestClient, db_path: Path) -> None:
    """Pre-populating the compare form with query parameters renders the side-by-side
    dimension digests, with each side's assertions collapsed by default (as in the prior
    contested-review view) and editable in place — the compare page is one of the primary
    places rulings get set, not just declared."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )
    _seed_opening(
        db_path,
        company_id="widgets",
        opening_id="widgets--b",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "stretch",
        },
    )
    assert response.status_code == 200
    assert "Synthetic digest" in response.text
    # The preview is blind to which openings are being compared: no company or opening
    # title is rendered (only the hidden form fields carry the ids for submission).
    assert 'class="compare-column-title"' not in response.text
    assert "acme--a title" not in response.text
    assert "widgets--b title" not in response.text
    # Assertions are collapsed by default, one <details> per side.
    assert response.text.count('<details class="assertion-context">') == 2
    assert response.text.count("assertion-snippet") == 2
    assert response.text.count("fit-indicator") == 2
    assert response.text.count("<blockquote>verbatim source text</blockquote>") == 2
    assert response.text.count('href="https://example.com/note"') == 2
    # Rulings are editable in place: a plain (non-htmx) form redirecting back to this
    # same comparison, not the rating page's HTMX partial swap.
    assert response.text.count('class="ruling-form"') == 2
    assert "hx-post" not in response.text
    redirect_url = "/compare?opening_a_id=acme--a&amp;opening_b_id=widgets--b&amp;target=stretch"
    assert response.text.count(f'name="redirect_to" value="{redirect_url}"') == 2


def test_compare_page_rejects_invalid_pair(client: TestClient, db_path: Path) -> None:
    """The compare GET rejects a pair that is missing, identical, or unknown."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )

    missing = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "no-such-opening",
            "target": "stretch",
        },
    )
    assert missing.status_code == 400

    same = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "acme--a",
            "target": "stretch",
        },
    )
    assert same.status_code == 400


def test_compare_form_uses_get_show_and_post_outcome_buttons(
    client: TestClient, db_path: Path
) -> None:
    """There is no selection UI: visiting `/compare` with no parameters auto-suggests a
    pair/dimension and renders the preview immediately, ready to judge."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )
    _seed_opening(
        db_path,
        company_id="widgets",
        opening_id="widgets--b",
        assertions=[_assertion("stretch", "Strong")],
    )
    auto = client.get("/compare")
    assert auto.status_code == 200
    assert '<form class="compare-form"' not in auto.text
    assert "Suggested comparison" not in auto.text
    assert 'class="compare-column-title"' not in auto.text
    assert "stretch" in auto.text
    assert auto.text.count('<form class="compare-actions" method="post" action="/compare">') == 1
    assert "Left wins" in auto.text
    assert "Right wins" in auto.text
    preview = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "stretch",
        },
    )
    assert preview.status_code == 200
    assert preview.text.count('<form class="compare-actions" method="post" action="/compare">') == 1
    assert "Left wins" in preview.text
    assert "Right wins" in preview.text


def test_compare_blank_form_when_no_suggestion(client: TestClient, db_path: Path) -> None:
    """When the picker cannot find a pair to compare, `/compare` renders an empty state
    instead of a preview."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )
    response = client.get("/compare")
    assert response.status_code == 200
    assert '<form class="compare-form"' not in response.text
    assert "Nothing to compare right now." in response.text
    assert "Left wins" not in response.text
    assert "Right wins" not in response.text


def test_compare_page_display_order_is_not_always_a_on_the_left(
    client: TestClient, db_path: Path
) -> None:
    """Which opening renders on the left is a deterministic function of the pair and
    dimension, not always the opening passed as `opening_a_id` — so position alone
    doesn't tell the operator which one is "A". Submitting a side's outcome still
    records the correct underlying opening."""
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("schematic", "Strong")],
    )
    _seed_opening(
        db_path,
        company_id="widgets",
        opening_id="widgets--b",
        assertions=[_assertion("schematic", "Strong")],
    )

    preview = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "schematic",
        },
    )
    assert preview.status_code == 200
    # For this pair/dimension the deterministic swap puts B on the left — the operator
    # never sees which underlying opening that is; the outcome button's value carries it.
    assert '<button type="submit" name="outcome" value="b">Left wins</button>' in preview.text
    assert '<button type="submit" name="outcome" value="a">Right wins</button>' in preview.text

    post_response = client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "schematic",
            "outcome": "b",  # "Left wins" button's value for this swapped pair
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 303

    conn = connect(db_path)
    rows = conn.execute("SELECT outcome FROM comparisons").fetchall()
    conn.close()
    assert dict(rows[0])["outcome"] == "b"


def test_compare_page_ruling_edit_redirects_back_to_same_comparison(
    client: TestClient, db_path: Path
) -> None:
    """Setting an assertion's fit from the compare page redirects back to the same
    comparison (not the rating page's HTMX partial), and the updated fit is reflected
    on reload — the compare page is a primary place rulings get set."""
    assertion = _assertion("stretch", "Mixed")
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[assertion],
    )
    _seed_opening(
        db_path,
        company_id="widgets",
        opening_id="widgets--b",
        assertions=[_assertion("stretch", "Strong")],
    )

    response = client.post(
        f"/openings/acme--a/assertions/{assertion.id}/ruling",
        data={
            "fit": "Strong",
            "redirect_to": "/compare?opening_a_id=acme--a&opening_b_id=widgets--b&target=stretch",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        "/compare?opening_a_id=acme--a&opening_b_id=widgets--b&target=stretch"
    )

    after = client.get(response.headers["location"])
    assert after.status_code == 200
    assert after.text.count('class="fit-segment fit-strong active"') == 4


@pytest.mark.parametrize(
    "field,value,expected_status",
    [
        ("target", "not-a-target", 400),
        ("opening_a_id", "no-such-opening", 404),
        ("opening_b_id", "no-such-opening", 404),
        ("outcome", "not-an-outcome", 400),
    ],
)
def test_submit_comparison_rejects_bad_input(
    client: TestClient,
    db_path: Path,
    field: str,
    value: str,
    expected_status: int,
) -> None:
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )
    _seed_opening(
        db_path,
        company_id="widgets",
        opening_id="widgets--b",
        assertions=[_assertion("stretch", "Strong")],
    )
    data = {
        "opening_a_id": "acme--a",
        "opening_b_id": "widgets--b",
        "target": "stretch",
        "outcome": "a",
    }
    data[field] = value
    response = client.post("/compare", data=data, follow_redirects=False)
    assert response.status_code == expected_status


def test_submit_comparison_rejects_same_opening(client: TestClient, db_path: Path) -> None:
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--a",
        assertions=[_assertion("stretch", "Strong")],
    )
    response = client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "acme--a",
            "target": "stretch",
            "outcome": "a",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_index_empty_queue_renders(client: TestClient) -> None:
    """An empty queue still returns a valid HTML document."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text


def test_index_queue_renders_median_marker_settledness_and_no_probability(
    client: TestClient, db_path: Path
) -> None:
    """The queue row replaces raw standing/reach/ceiling floats and any decimal
    probability with the shared boundary glyph; with fewer than `top_k` openings
    there is no boundary yet, so the median marker renders fully settled (alpha 1)."""
    config = load_scoring_config()
    strong = [_assertion(slug, "Strong") for slug in (*config.dimension_weights,)]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=strong)
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "boundary-glyph" in body
    assert "crossing_probability" not in body
    assert "% chance" not in body
    assert "rank-band" not in body
    assert re.search(r"--settledness:\s*1\.0", body) is not None
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


def test_index_queue_median_marker_settledness_reflects_top_k_straddle(
    client: TestClient, db_path: Path
) -> None:
    """Once the pool exceeds `top_k` size, an opening near the boundary whose rank band
    straddles it renders a partial (not full, not zero) settledness alpha."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
    for i in range(config.top_k + 3):
        fit: Fit = "Strong" if i % 2 == 0 else "Mixed"
        _seed_opening(
            db_path,
            company_id=f"c{i}",
            opening_id=f"c{i}--eng",
            assertions=[
                Assertion(
                    target=slug,  # type: ignore[arg-type]
                    fit=fit,
                    provenance="model_proposed",
                    chunk="verbatim source text",
                    citations=[_CITATION],
                    created_at=_NOW,
                )
                for slug in targets
            ],
        )
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert re.search(r"--settledness:\s*0\.6\b", body) is not None


def test_index_queue_median_marker_settledness_is_zero_when_fully_outside_top_k(
    client: TestClient, db_path: Path
) -> None:
    """An opening whose entire rank band sits worse than the top-K boundary renders an
    outline-only median marker (alpha 0) and the 'outside' settledness label."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
    for i in range(config.top_k):
        _seed_opening(
            db_path,
            company_id=f"c{i}",
            opening_id=f"c{i}--eng",
            assertions=[_assertion(slug, "Strong") for slug in targets],
        )
    _seed_opening(
        db_path,
        company_id="tail",
        opening_id="tail--eng",
        assertions=[_assertion(slug, "Poor") for slug in targets],
    )

    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert re.search(r"--settledness:\s*0\.0\b", body) is not None
    assert "outside the top 5" in body


def test_rate_opening_score_block_renders_median_marker_settledness_and_no_probability(
    client: TestClient, db_path: Path
) -> None:
    """The per-opening score block replaces raw floats and any decimal probability
    with the same boundary glyph the queue uses."""
    config = load_scoring_config()
    strong = [_assertion(slug, "Strong") for slug in (*config.dimension_weights,)]
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng", assertions=strong)
    response = client.get("/openings/acme--eng/rate")
    assert response.status_code == 200
    body = response.text
    assert "boundary-glyph" in body
    assert "crossing_probability" not in body
    assert "% chance" not in body
    assert "rank-band" not in body
    assert "--settledness:" in body
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
    strong = [_assertion(slug, "Strong") for slug in (*config.dimension_weights,)]
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


def test_submit_ruling_ignores_off_site_redirect_to(client: TestClient, db_path: Path) -> None:
    """`redirect_to` only honors same-origin relative paths — an absolute or
    protocol-relative URL is ignored and the usual HTMX partial is returned instead of
    an open redirect."""
    assertion = _assertion("stretch", "Mixed")
    _seed_opening(
        db_path,
        company_id="acme",
        opening_id="acme--eng",
        assertions=[assertion],
    )

    response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling",
        data={"fit": "Strong", "redirect_to": "//evil.example.com/"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert 'id="rating-content"' in response.text


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
    targets = (*config.dimension_weights,)
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
    assert 'title="locked into top ' in body


def test_rate_opening_score_block_shares_boundary_glyph_macro_with_queue(
    client: TestClient, db_path: Path
) -> None:
    """The per-opening score block renders the same marks (interval band, median dot,
    boundary tick) as the queue row, via the shared `boundary_glyph` macro."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
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


def _seed_live_opening(db_path: Path, opening_id: str) -> None:
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
        deps_factory=lambda: RunDispatchDeps(
            browser=FakeBrowser(search_fixtures={"paused query": []}),
            extractor=FakeExtractor([[_assertion("stretch", "Strong")]]),
            digester=FakeDigester(["Synthetic digest."]),
        ),
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
        assert "Researching" in response.text
        # The response must land before the gate is released.
        assert t1 - t0 < 0.5

        # Poll the status endpoint while the batch is still blocked.
        for _ in range(50):
            status = client.get(f"{base}/batch-status")
            assert status.status_code == 200
            if "Researching" in status.text:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("batch did not show running status")

        # Now let the background task finish its first (and only) turn.
        gate.set()
        for _ in range(50):
            status = client.get(f"{base}/batch-status")
            if "Researching" not in status.text:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("batch never finished")
        assert "Researching" not in status.text

        # One turn was actually spent (2 turns total: 1 seeded + 1 from the batch).
        conn = connect(db_path)
        opening = get_opening(conn, "acme--eng")
        assert opening is not None
        trace_path = research_trace_path_for(db_path.parent, opening.research_trace_id)
        used = replay_research_trace(trace_path).turns_used
        conn.close()
        assert used == 2


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
        assert "Researching" in first.text

        second = client.post(f"{base}/batch", data={"batch_size": "3"})
        assert second.status_code == 200
        assert "already running" in second.text

        gate.set()


def test_queue_hides_research_turns_used_and_budget(client: TestClient, db_path: Path) -> None:
    """Queue rows no longer show the turns-used/budget counter (queue-page-cleanup
    bearing, Done When)."""
    _seed_live_opening(db_path, "acme--eng")
    response = client.get("/")
    assert response.status_code == 200
    assert "research-status" not in response.text
    assert "1/5" not in response.text


def test_batch_start_form_validates_batch_size(client: TestClient) -> None:
    """The batch start form rejects non-positive batch sizes."""
    response = client.post("/batch", data={"batch_size": "0"})
    assert response.status_code == 422


def test_batch_start_defaults_to_50_turns_when_omitted(client: TestClient) -> None:
    """The queue page's single start button posts no visible batch_size; the server
    defaults to 50 turns (queue-page-cleanup bearing, Done When)."""
    response = client.post("/batch", data={})
    assert response.status_code == 200
    assert "Researching" in response.text


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
    targets = (*config.dimension_weights,)
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
    """The rating view exposes a way to change an opening's stage — the same page the
    operator already reviews the opening from."""
    _seed_opening(db_path, company_id="acme", opening_id="acme--eng")

    response = client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    assert "/openings/acme--eng/stage" in response.text
    for stage in ("screening", "pursuing", "applied", "closed"):
        assert stage in response.text


def test_archive_view_lists_openings_by_stage(client: TestClient, db_path: Path) -> None:
    """`/archive` lists every non-`screening` opening, filterable by stage, each linking
    back to its existing rating view for recall."""
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


def test_retired_routes_return_404(client: TestClient) -> None:
    """The old contested/focus sessions and dimension-ruling POST are gone; requests
    to their former URLs fall through to a 404 instead of resurrecting stale surfaces."""
    assert client.get("/contested").status_code == 404
    assert client.get("/openings/acme--eng/contested").status_code == 404
    assert client.get("/openings/acme--eng/focus").status_code == 404
    assert (
        client.post(
            "/openings/acme--eng/dimensions/stretch/ruling",
            data={"mean": 0.0, "settledness": 0.5},
        ).status_code
        == 404
    )
