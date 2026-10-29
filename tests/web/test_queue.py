"""Integration tests for the ranked queue and the per-opening rating view."""

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from screen.digest.fakes import FakeDigester
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.mappers import assertion_ruling_to_row
from screen.store.repo import (
    append_assertions,
    append_comparison,
    assertion_rulings_for_opening,
    assertions_for_opening,
    get_opening,
    insert_dimension_digest,
    upsert_company,
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
)
from tests.helpers import canned_assertion, canned_citation, make_app, seed_opening
from tests.web.helpers import (
    NOW,
    boundary_glyph_positions,
)


def test_rate_opening_makes_no_live_digest_calls_when_cache_is_warm(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    """A warm cache means the rating view never calls the digester — cold-cache
    generation happens post-pass, not on page view."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="craft_direction",
        digest="High-bar stretch culture.",
        assertion_count=1,
        computed_at=NOW,
    )
    digester = FakeDigester(["unused"])
    app = make_app(db_path, digester=digester)

    with TestClient(app) as test_client:
        response = test_client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    assert digester.calls == 0


def test_index_renders_queue_html(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """`GET /` returns text/html with the ranked queue."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "acme Inc" in body
    assert "acme--eng title" in body
    assert "rate" in body


def test_index_order_matches_json_queue(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The HTML queue renders in the same standing order as `GET /queue`."""
    config = load_scoring_config()
    strong = [canned_assertion(slug, "Strong", "ratified") for slug in (*config.dimension_weights,)]
    seed_opening(conn, "acme--strong", assertions=strong)
    seed_opening(conn, "widgets--unexamined")

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


def test_index_queue_reorders_after_assertion_ruling(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Submitting a ruling that raises an opening's standing re-sorts the HTML queue and
    the JSON queue in the same way."""
    config = load_scoring_config()
    poor_assertions = [
        Assertion(
            target=slug,  # type: ignore[arg-type]
            fit="Poor",
            provenance="model_proposed",
            chunk="verbatim source text",
            citations=[canned_citation()],
            created_at=NOW,
        )
        for slug in (*config.dimension_weights,)
    ]
    seed_opening(conn, "acme--ruled", assertions=poor_assertions)
    seed_opening(conn, "widgets--unexamined")

    before = client.get("/")
    assert before.status_code == 200
    assert before.text.find("widgets--unexamined") < before.text.find("acme--ruled")

    for assertion in assertions_for_opening(conn, "acme--ruled"):
        response = client.post(
            f"/openings/acme--ruled/assertions/{assertion.id}/ruling",
            data={"fit": "Strong"},
        )
        assert response.status_code == 200

    after = client.get("/")
    assert after.status_code == 200
    assert after.text.find("acme--ruled") < after.text.find("widgets--unexamined")

    json_response = client.get("/queue")
    assert json_response.status_code == 200
    json_ids = [item["opening_id"] for item in json_response.json()]
    assert json_ids == ["acme--ruled", "widgets--unexamined"]


def test_index_queue_reorders_after_comparison(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """A stored comparison must reach the same `_ranked_pool` the HTML queue and JSON
    `/queue` both render from — the wiring `pool_for_screening`'s comparison args
    depend on (`comparisons_by_target`/`companies_by_opening`), not just the pure fit."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    seed_opening(
        conn,
        "widgets--b",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )

    before = client.get("/")
    assert before.status_code == 200

    for _ in range(3):
        append_comparison(
            conn,
            Comparison(
                opening_a_id="widgets--b",
                opening_b_id="acme--a",
                target="craft_direction",
                outcome="a",
                predicted_a_beats_b=0.5,
                created_at=NOW,
            ),
        )

    after = client.get("/")
    assert after.status_code == 200
    assert after.text.find("widgets--b") < after.text.find("acme--a")

    json_response = client.get("/queue")
    assert json_response.status_code == 200
    json_ids = [item["opening_id"] for item in json_response.json()]
    assert json_ids == ["widgets--b", "acme--a"]


def test_index_empty_queue_renders(client: TestClient) -> None:
    """An empty queue still returns a valid HTML document."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text


def test_index_queue_renders_median_marker_settledness_and_no_probability(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The queue row replaces raw standing/reach/ceiling floats and any decimal
    probability with the shared boundary glyph; with fewer than `top_k` openings
    there is no boundary yet, so the median marker renders fully settled (alpha 1)."""
    config = load_scoring_config()
    strong = [canned_assertion(slug, "Strong", "ratified") for slug in (*config.dimension_weights,)]
    seed_opening(conn, "acme--eng", assertions=strong)
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
    median, range_left, range_right = boundary_glyph_positions(row_match.group(0))
    assert range_left <= median <= range_right


def test_index_queue_median_marker_settledness_reflects_top_k_straddle(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Once the pool exceeds `top_k` size, an opening near the boundary whose rank band
    straddles it renders a partial (not full, not zero) settledness alpha."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
    for i in range(config.top_k + 3):
        fit: Fit = "Strong" if i % 2 == 0 else "Mixed"
        seed_opening(
            conn,
            f"c{i}--eng",
            assertions=[
                Assertion(
                    target=slug,  # type: ignore[arg-type]
                    fit=fit,
                    provenance="model_proposed",
                    chunk="verbatim source text",
                    citations=[canned_citation()],
                    created_at=NOW,
                )
                for slug in targets
            ],
        )
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert re.search(r"--settledness:\s*0\.6\b", body) is not None


def test_index_queue_median_marker_settledness_is_zero_when_fully_outside_top_k(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """An opening whose entire rank band sits worse than the top-K boundary renders an
    outline-only median marker (alpha 0) and the 'outside' settledness label."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
    for i in range(config.top_k):
        seed_opening(
            conn,
            f"c{i}--eng",
            assertions=[canned_assertion(slug, "Strong", "ratified") for slug in targets],
        )
    seed_opening(
        conn,
        "tail--eng",
        assertions=[canned_assertion(slug, "Poor", "ratified") for slug in targets],
    )

    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert re.search(r"--settledness:\s*0\.0\b", body) is not None
    assert f"outside the top {config.top_k}" in body


def test_rate_opening_score_block_renders_median_marker_settledness_and_no_probability(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The per-opening score block replaces raw floats and any decimal probability
    with the same boundary glyph the queue uses."""
    config = load_scoring_config()
    strong = [canned_assertion(slug, "Strong", "ratified") for slug in (*config.dimension_weights,)]
    seed_opening(conn, "acme--eng", assertions=strong)
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
    median, range_left, range_right = boundary_glyph_positions(body)
    assert range_left <= median <= range_right


def test_rate_opening_groups_assertions_by_dimension(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Assertions are grouped under their target dimension heading instead of a flat list."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[
            canned_assertion("craft_direction", "Strong", "ratified"),
            canned_assertion("mission", "Mixed", "ratified"),
        ],
    )

    response = client.get("/openings/acme--eng/rate")

    assert response.status_code == 200
    body = response.text
    assert '<h3 class="dimension-title">craft_direction</h3>' in body
    assert '<h3 class="dimension-title">mission</h3>' in body
    # Each dimension's assertion appears in its own section.
    stretch_heading = body.index('<h3 class="dimension-title">craft_direction</h3>')
    mission_heading = body.index('<h3 class="dimension-title">mission</h3>')
    next_after_stretch = body.find('<h3 class="dimension-title">', stretch_heading + 1)
    stretch_section = body[stretch_heading:next_after_stretch]
    assert "fit-strong active" in stretch_section
    next_after_mission = body.find('<h3 class="dimension-title">', mission_heading + 1)
    mission_section = body[mission_heading:next_after_mission]
    assert "fit-mixed active" in mission_section


def test_rate_opening_shows_cached_digest_above_assertions(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Each dimension group shows its cached digest above the assertion list."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="craft_direction",
        digest="High-bar stretch culture.",
        assertion_count=1,
        computed_at=NOW,
    )

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert body.count("High-bar stretch culture.") == 1
    digest_pos = body.find("High-bar stretch culture.")
    chunk_pos = body.find("Synthetic fixture content.")
    assert digest_pos < chunk_pos


def test_rate_opening_dimension_order_is_weight_descending(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Dimension groups render in weight-descending order, not assertion insertion order."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[
            canned_assertion("domain", "Mixed", "ratified"),  # weight 1
            canned_assertion("craft_direction", "Strong", "ratified"),  # weight 3
        ],
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="craft_direction",
        digest="Stretch digest.",
        assertion_count=1,
        computed_at=NOW,
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="domain",
        digest="Domain digest.",
        assertion_count=1,
        computed_at=NOW,
    )

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert body.count("Stretch digest.") == 1
    assert body.count("Domain digest.") == 1
    assert body.find("Stretch digest.") < body.find("Domain digest.")


def test_rate_opening_empty_dimension_shows_not_yet_examined(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """A dimension with no assertions renders its group with a 'not yet examined' digest."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="craft_direction",
        digest="Stretch digest.",
        assertion_count=1,
        computed_at=NOW,
    )

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    mission_heading = body.index('<h3 class="dimension-title">mission</h3>')
    next_after_mission = body.find('<h3 class="dimension-title">', mission_heading + 1)
    mission_section = body[mission_heading:next_after_mission]
    assert "not yet examined" in mission_section


def test_rate_opening_renders_bullets_and_line_breaks_as_html(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """A digest with leading-dash bullets and line breaks renders as `<ul>/<li>`
    or `<br>`, not literal text."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="craft_direction",
        digest="Evidence is mixed:\n- Autonomy is real.\n- Process is heavy.",
        assertion_count=1,
        computed_at=NOW,
    )

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert "<ul>" in body
    assert "<li>Autonomy is real.</li>" in body
    assert "<li>Process is heavy.</li>" in body
    assert "- Autonomy is real." not in body


def test_rate_opening_per_assertion_rendering_unchanged(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The per-assertion markup (fit control, provenance glyph, quote) stays stable across
    dimension grouping; the target itself isn't repeated per assertion since the dimension
    heading above already names it."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="craft_direction",
        digest="Stretch digest.",
        assertion_count=1,
        computed_at=NOW,
    )

    response = client.get("/openings/acme--eng/rate")
    body = response.text

    assert "fit-strong active" in body
    assert 'title="ratified"' in body
    assert "<blockquote>Synthetic fixture content.</blockquote>" in body


def test_rate_opening_404_when_missing(client: TestClient) -> None:
    """A missing opening returns 404, not an error page."""
    response = client.get("/openings/no-such-opening/rate")
    assert response.status_code == 404


def test_rate_opening_renders_citation_link(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Each assertion's citation renders as a clickable link to its `url`."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )

    response = client.get("/openings/acme--eng/rate")

    body = response.text
    assert f'href="{canned_citation().url}"' in body
    assert canned_citation().host in body


def test_rate_opening_shows_model_proposed_provenance(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """An assertion with no recorded ruling shows its provenance as a compact glyph
    and renders the fit control active at the model's proposed value."""
    seed_opening(
        conn,
        "acme--eng",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )

    response = client.get("/openings/acme--eng/rate")

    body = response.text
    assert "provenance-glyph" in body
    assert 'title="ratified"' in body
    assert 'value="Strong"' in body
    assert "fit-strong active" in body


def test_rate_opening_shows_existing_ruling_in_fit_control(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """An `AssertionRuling` already recorded for an assertion makes the control's
    active segment reflect the operator's value, not the original proposal."""
    assertion = canned_assertion("craft_direction", "Mixed", "ratified")
    seed_opening(
        conn,
        "acme--eng",
        assertions=[assertion],
    )
    ruling = AssertionRuling(assertion_id=assertion.id, fit="Strong", created_at=NOW)
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
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Once an operator ruling exists for an assertion, the glyph shows `ratified`
    (the operator's own review), not the model's original provenance — the glyph
    signals "has this been reviewed," not the assertion's frozen history."""
    assertion = Assertion(
        target="internal_culture",
        fit="Strong",
        provenance="model_proposed",
        chunk="verbatim source text",
        citations=[canned_citation()],
        created_at=NOW,
    )
    seed_opening(
        conn,
        "acme--eng",
        assertions=[assertion],
    )
    ruling = AssertionRuling(assertion_id=assertion.id, fit="Mixed", created_at=NOW)
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


def test_submit_ruling_writes_and_swaps_partial(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """POSTing an override writes an `AssertionRuling` and returns the rating content
    partial (not a full document) reflecting the new ruling — an HTMX partial swap,
    not a full-document GET."""
    assertion = canned_assertion("craft_direction", "Mixed", "ratified")
    seed_opening(
        conn,
        "acme--eng",
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

    rulings = assertion_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].assertion_id == assertion.id
    assert rulings[0].fit == "Strong"


def test_submit_ruling_confirming_current_value_still_ratifies(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Clicking the already-active segment is an explicit confirm, not a no-op —
    it still records a ruling and flips the glyph to `ratified`."""
    assertion = Assertion(
        target="craft_direction",
        fit="Strong",
        provenance="model_proposed",
        chunk="verbatim source text",
        citations=[canned_citation()],
        created_at=NOW,
    )
    seed_opening(
        conn,
        "acme--eng",
        assertions=[assertion],
    )

    response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Strong"}
    )

    assert response.status_code == 200
    assert 'title="ratified"' in response.text

    rulings = assertion_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].fit == "Strong"


def test_submit_ruling_changes_the_score(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Submitting a ruling changes the rendered standing when it flips a target's fit."""
    config = load_scoring_config()
    strong = [canned_assertion(slug, "Strong", "ratified") for slug in (*config.dimension_weights,)]
    seed_opening(conn, "acme--eng", assertions=strong)
    stretch_assertion = next(a for a in strong if a.target == "craft_direction")

    before = client.get("/openings/acme--eng/rate")
    response = client.post(
        f"/openings/acme--eng/assertions/{stretch_assertion.id}/ruling", data={"fit": "Poor"}
    )

    assert response.status_code == 200
    assert "boundary-glyph" in response.text
    assert response.text != before.text


def test_submit_ruling_replaces_prior_ruling_for_same_assertion(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Re-submitting an override for the same assertion replaces the stored ruling."""
    assertion = canned_assertion("craft_direction", "Mixed", "ratified")
    seed_opening(
        conn,
        "acme--eng",
        assertions=[assertion],
    )

    client.post(f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Strong"})
    client.post(f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Poor"})

    rulings = assertion_rulings_for_opening(conn, "acme--eng")
    assert len(rulings) == 1
    assert rulings[0].fit == "Poor"


def test_submit_ruling_404_when_opening_missing(client: TestClient) -> None:
    response = client.post(
        "/openings/no-such-opening/assertions/no-such-assertion/ruling", data={"fit": "Strong"}
    )
    assert response.status_code == 404


def test_submit_ruling_ignores_off_site_redirect_to(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """`redirect_to` only honors same-origin relative paths — an absolute or
    protocol-relative URL is ignored and the usual HTMX partial is returned instead of
    an open redirect."""
    assertion = canned_assertion("craft_direction", "Mixed", "ratified")
    seed_opening(
        conn,
        "acme--eng",
        assertions=[assertion],
    )

    response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling",
        data={"fit": "Strong", "redirect_to": "//evil.example.com/"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert 'id="rating-content"' in response.text


def test_submit_ruling_rejects_invalid_fit(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    assertion = canned_assertion("craft_direction", "Mixed", "ratified")
    seed_opening(
        conn,
        "acme--eng",
        assertions=[assertion],
    )

    response = client.post(
        f"/openings/acme--eng/assertions/{assertion.id}/ruling", data={"fit": "Excellent"}
    )

    assert response.status_code == 422


def test_index_queue_hides_boundary_tick_when_fewer_than_top_k(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """With fewer than `top_k` scored openings there is no K-th opening, so the queue
    row's glyph has no boundary tick and no crossing-probability tooltip — the boundary
    does not exist yet."""
    seed_opening(conn, "acme--eng")

    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "boundary-glyph" in body
    assert "boundary-tick" not in body
    assert "chance of crossing the boundary" not in body


def test_index_queue_shows_boundary_tick_when_at_least_top_k(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """With at least `top_k` scored openings the K-th opening exists, so every row's
    glyph shows a boundary tick and a crossing-probability tooltip."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
    for i in range(config.top_k):
        seed_opening(
            conn,
            f"c{i}--eng",
            assertions=[canned_assertion(slug, "Strong", "ratified") for slug in targets],
        )

    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "boundary-tick" in body
    assert 'title="locked into top ' in body


def test_rate_opening_score_block_shares_boundary_glyph_macro_with_queue(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The per-opening score block renders the same marks (interval band, median dot,
    boundary tick) as the queue row, via the shared `boundary_glyph` macro."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
    for i in range(config.top_k):
        seed_opening(
            conn,
            f"c{i}--eng",
            assertions=[canned_assertion(slug, "Strong", "ratified") for slug in targets],
        )

    response = client.get("/openings/c0--eng/rate")

    assert response.status_code == 200
    body = response.text
    assert "boundary-glyph" in body
    for mark in ("boundary-range", "boundary-median", "boundary-tick"):
        assert mark in body


def test_queue_excludes_openings_not_in_screening_stage(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The ranked HTML queue and the JSON `/queue` only ever list `screening`-stage
    openings — `pursuing`/`applied`/`closed` openings leave the live queue."""
    seed_opening(conn, "acme--screening")
    seed_opening(conn, "widgets--pursuing", stage="pursuing")
    seed_opening(conn, "globex--applied", stage="applied")
    seed_opening(conn, "initech--closed", stage="closed")

    html = client.get("/")
    json_response = client.get("/queue")

    assert html.status_code == 200
    assert "acme--screening" in html.text
    for excluded in ("widgets--pursuing", "globex--applied", "initech--closed"):
        assert excluded not in html.text

    json_ids = [item["opening_id"] for item in json_response.json()]
    assert json_ids == ["acme--screening"]


def test_moving_opening_out_of_screening_drops_it_from_boundary_computation(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """A de-queued opening never anchors the `top_k` boundary — moving the K-th-ranked
    opening out of `screening` shifts the boundary to the new K-th opening."""
    config = load_scoring_config()
    targets = (*config.dimension_weights,)
    for i in range(config.top_k + 1):
        seed_opening(
            conn,
            f"c{i}--eng",
            assertions=[canned_assertion(slug, "Strong", "ratified") for slug in targets],
        )

    before = client.get("/queue").json()
    assert len(before) == config.top_k + 1

    top_opening = get_opening(conn, before[0]["opening_id"])
    assert top_opening is not None
    upsert_opening(conn, top_opening.model_copy(update={"stage": "applied"}))

    after = client.get("/queue").json()
    assert len(after) == config.top_k
    assert before[0]["opening_id"] not in [item["opening_id"] for item in after]


def test_index_queue_identifies_stale_items(client: TestClient, db_path: Path) -> None:
    conn = connect(db_path)
    now = datetime.now(UTC)
    upsert_company(conn, Company(id="co", name="Co", created_at=now))
    o1 = Opening(
        id="o1",
        company_id="co",
        title="O1",
        url="http://o1",
        research_trace_id="t1",
        created_at=now - timedelta(days=20),
    )
    upsert_opening(conn, o1)
    append_assertions(
        conn,
        [
            Assertion(
                id="a1",
                target="craft_direction",
                fit="Strong",
                provenance="ratified",
                chunk="test chunk",
                citations=[
                    Citation(
                        url="http://test",
                        host="test",
                        source_provenance="company-owned",
                        independent=True,
                        quote="test quote",
                    )
                ],
                created_at=now,
            )
        ],
        opening_id="o1",
    )
    o2 = Opening(
        id="o2",
        company_id="co",
        title="O2",
        url="http://o2",
        research_trace_id="t2",
        created_at=now - timedelta(days=30),
    )
    upsert_opening(conn, o2)
    append_assertions(
        conn,
        [
            Assertion(
                id="a2",
                target="craft_direction",
                fit="Mixed",
                provenance="ratified",
                chunk="test chunk",
                citations=[
                    Citation(
                        url="http://test",
                        host="test",
                        source_provenance="company-owned",
                        independent=True,
                        quote="test quote",
                    )
                ],
                created_at=now,
            )
        ],
        opening_id="o2",
    )
    o3 = Opening(
        id="o3",
        company_id="co",
        title="O3",
        url="http://o3",
        research_trace_id="t3",
        created_at=now - timedelta(days=15),
    )
    upsert_opening(conn, o3)
    append_assertions(
        conn,
        [
            Assertion(
                id="a3",
                target="craft_direction",
                fit="Poor",
                provenance="ratified",
                chunk="test chunk",
                citations=[
                    Citation(
                        url="http://test",
                        host="test",
                        source_provenance="company-owned",
                        independent=True,
                        quote="test quote",
                    )
                ],
                created_at=now,
            )
        ],
        opening_id="o3",
    )
    response = client.get("/")
    assert response.status_code == 200
    assert "is-stale" in response.text


def test_prune_stale_moves_only_stale_items_to_closed(client: TestClient, db_path: Path) -> None:
    conn = connect(db_path)
    now = datetime.now(UTC)

    upsert_company(conn, Company(id="co", name="Co", created_at=now))

    # rank 1: age 20 (not stale)
    o1 = Opening(
        id="o1",
        company_id="co",
        title="O1",
        url="http://o1",
        research_trace_id="t1",
        created_at=now - timedelta(days=20),
    )
    upsert_opening(conn, o1)
    append_assertions(
        conn,
        [
            Assertion(
                id="a1",
                target="craft_direction",
                fit="Strong",
                provenance="ratified",
                chunk="test chunk",
                citations=[
                    Citation(
                        url="http://test",
                        host="test",
                        source_provenance="company-owned",
                        independent=True,
                        quote="test quote",
                    )
                ],
                created_at=now,
            )
        ],
        opening_id="o1",
    )

    # rank 2: age 30 (stale)
    o2 = Opening(
        id="o2",
        company_id="co",
        title="O2",
        url="http://o2",
        research_trace_id="t2",
        created_at=now - timedelta(days=30),
    )
    upsert_opening(conn, o2)
    append_assertions(
        conn,
        [
            Assertion(
                id="a2",
                target="craft_direction",
                fit="Mixed",
                provenance="ratified",
                chunk="test chunk",
                citations=[
                    Citation(
                        url="http://test",
                        host="test",
                        source_provenance="company-owned",
                        independent=True,
                        quote="test quote",
                    )
                ],
                created_at=now,
            )
        ],
        opening_id="o2",
    )

    # rank 3: age 15 (not stale yet, threshold is 26)
    o3 = Opening(
        id="o3",
        company_id="co",
        title="O3",
        url="http://o3",
        research_trace_id="t3",
        created_at=now - timedelta(days=15),
    )
    upsert_opening(conn, o3)
    append_assertions(
        conn,
        [
            Assertion(
                id="a3",
                target="craft_direction",
                fit="Poor",
                provenance="ratified",
                chunk="test chunk",
                citations=[
                    Citation(
                        url="http://test",
                        host="test",
                        source_provenance="company-owned",
                        independent=True,
                        quote="test quote",
                    )
                ],
                created_at=now,
            )
        ],
        opening_id="o3",
    )

    response = client.post("/prune-stale", follow_redirects=False)
    assert response.status_code in (302, 303)

    assert get_opening(conn, "o1").stage == "screening"
    assert get_opening(conn, "o2").stage == "closed"
    assert get_opening(conn, "o3").stage == "screening"


def test_retired_routes_return_404(client: TestClient) -> None:
    """The old contested/focus sessions and dimension-ruling POST are gone; requests
    to their former URLs fall through to a 404 instead of resurrecting stale surfaces."""
    assert client.get("/contested").status_code == 404
    assert client.get("/openings/acme--eng/contested").status_code == 404
    assert client.get("/openings/acme--eng/focus").status_code == 404
    assert (
        client.post(
            "/openings/acme--eng/dimensions/craft_direction/ruling",
            data={"mean": 0.0, "settledness": 0.5},
        ).status_code
        == 404
    )
