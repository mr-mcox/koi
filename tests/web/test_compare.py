"""Integration tests for the comparison surface and its pre-screen cache."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from screen.compare.picker import ComparisonSuggestion
from screen.compare.prescreen import CompareCache
from screen.store.repo import (
    append_comparison,
    get_dimension_digest,
)
from screen.types import (
    Comparison,
)
from screen.verdict.protocol import RubricVerdict
from tests.helpers import canned_assertion, seed_opening
from tests.web.helpers import (
    NOW,
    live_state,
    settled_compare_page,
)


def test_compare_page_reachable_from_queue_and_submits_winner(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The operator can pick any two openings and a scoring dimension, submit that A
    beats B, and the queue immediately reorders through the same comparison-fitted
    pool. The stored comparison row carries the pre-comparison probability computed
    from assertion priors."""
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

    queue = client.get("/")
    assert queue.status_code == 200
    assert 'href="/compare"' in queue.text

    get_response = settled_compare_page(client)
    assert get_response.status_code == 200
    assert "craft_direction" in get_response.text
    assert 'class="compare-column-title"' not in get_response.text

    post_response = client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "craft_direction",
            "outcome": "a",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    assert post_response.headers["location"] == "/compare"

    rows = conn.execute(
        "SELECT opening_a_id, opening_b_id, target, outcome, predicted_a_beats_b FROM comparisons"
    ).fetchall()
    assert len(rows) == 1
    assert dict(rows[0]) == {
        "opening_a_id": "acme--a",
        "opening_b_id": "widgets--b",
        "target": "craft_direction",
        "outcome": "a",
        "predicted_a_beats_b": pytest.approx(0.5),
    }

    after = client.get("/")
    assert after.status_code == 200
    assert after.text.find("acme--a") < after.text.find("widgets--b")

    json_response = client.get("/queue")
    assert json_response.status_code == 200
    assert [item["opening_id"] for item in json_response.json()] == ["acme--a", "widgets--b"]


def test_compare_page_previews_target_digests(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Pre-populating the compare form with query parameters renders the side-by-side
    dimension digests, with each side's assertions collapsed by default (as in the prior
    contested-review view) and editable in place — the compare page is one of the primary
    places rulings get set, not just declared."""
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

    response = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "craft_direction",
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
    assert response.text.count("<blockquote>Synthetic fixture content.</blockquote>") == 2
    assert response.text.count('href="https://example.com/jobs/42"') == 2
    # Rulings are editable in place: a plain (non-htmx) form redirecting back to this
    # same comparison, not the rating page's HTMX partial swap.
    assert response.text.count('class="ruling-form"') == 2
    assert "hx-post" not in response.text
    redirect_url = (
        "/compare?opening_a_id=acme--a&amp;opening_b_id=widgets--b&amp;target=craft_direction"
    )
    assert response.text.count(f'name="redirect_to" value="{redirect_url}"') == 2


def test_compare_page_and_submission_carry_digest_versions(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The compare GET renders a durable digest-version id per side as a hidden form
    field, and the POST persists those versions on the stored `Comparison` — the
    evidence provenance the operator actually judged against, not a placeholder."""
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

    response = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "craft_direction",
        },
    )
    assert response.status_code == 200
    assert 'name="opening_a_digest_version"' in response.text
    assert 'name="opening_b_digest_version"' in response.text

    digest_a = get_dimension_digest(conn, "acme--a", "craft_direction")
    digest_b = get_dimension_digest(conn, "widgets--b", "craft_direction")
    assert digest_a is not None
    assert digest_b is not None

    post_response = client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "craft_direction",
            "outcome": "a",
            "opening_a_digest_version": digest_a.id,
            "opening_b_digest_version": digest_b.id,
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 303

    row = conn.execute(
        "SELECT opening_a_digest_version, opening_b_digest_version FROM comparisons"
    ).fetchone()
    assert dict(row) == {
        "opening_a_digest_version": digest_a.id,
        "opening_b_digest_version": digest_b.id,
    }


def test_compare_page_rejects_invalid_pair(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The compare GET rejects a pair that is missing, identical, or unknown."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )

    missing = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "no-such-opening",
            "target": "craft_direction",
        },
    )
    assert missing.status_code == 400

    same = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "acme--a",
            "target": "craft_direction",
        },
    )
    assert same.status_code == 400


def test_compare_form_uses_get_show_and_post_outcome_buttons(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """There is no selection UI: visiting `/compare` with no parameters auto-suggests a
    pair/dimension and renders the preview immediately, ready to judge."""
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
    auto = settled_compare_page(client)
    assert auto.status_code == 200
    assert '<form class="compare-form"' not in auto.text
    assert "Suggested comparison" not in auto.text
    assert 'class="compare-column-title"' not in auto.text
    assert "craft_direction" in auto.text
    assert auto.text.count('<form class="compare-actions" method="post" action="/compare">') == 1
    assert "Left wins" in auto.text
    assert "Right wins" in auto.text
    preview = client.get(
        "/compare",
        params={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "craft_direction",
        },
    )
    assert preview.status_code == 200
    assert preview.text.count('<form class="compare-actions" method="post" action="/compare">') == 1
    assert "Left wins" in preview.text
    assert "Right wins" in preview.text


def test_compare_blank_form_when_no_suggestion(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """When the picker cannot find a pair to compare, `/compare` renders an empty state
    instead of a preview."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    response = settled_compare_page(client)
    assert response.status_code == 200
    assert '<form class="compare-form"' not in response.text
    assert "Nothing to compare right now." in response.text
    assert "Left wins" not in response.text
    assert "Right wins" not in response.text


def test_compare_status_shows_prescreen_progress_then_redirects_when_done(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """`/compare-status` renders the live `ruled` list while a pre-screen pass is in
    flight, and once it finishes it tells HTMX to reload `/compare` (`HX-Redirect`) rather
    than rendering a comparison itself."""
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

    triggering = client.get("/compare")
    assert triggering.status_code == 200

    status = client.get("/compare-status")
    assert status.status_code == 200
    assert "HX-Redirect" in status.headers
    assert status.headers["HX-Redirect"] == "/compare"


def test_compare_status_omits_redirect_while_still_running(
    client: TestClient, db_path: Path
) -> None:
    """While a pre-screen pass is genuinely still running, `/compare-status` must not
    tell HTMX to redirect — that would bounce the operator back to `/compare` before
    Jev's pass has a result to show."""
    live_state(client).compare.progress.running = True

    status = client.get("/compare-status")

    assert status.status_code == 200
    assert "HX-Redirect" not in status.headers
    assert "compare-prescreening" in status.text


def test_compare_page_uses_stale_by_one_cache_when_pair_still_legal(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """A cached compare suggestion from the previous compare-write version is still good
    enough to render immediately as long as the pair is still legal; the fresh prescreen
    can keep running behind it."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    seed_opening(
        conn,
        "widgets--b",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    live_state(client).compare.cache = CompareCache(
        version=0,
        suggestion=ComparisonSuggestion(
            target="location",
            opening_a_id="acme--a",
            opening_b_id="widgets--b",
        ),
        jev_read=RubricVerdict(outcome="tie", confidence=0.62),
    )
    live_state(client).compare.state.version = 1
    live_state(client).compare.state.last_write = (frozenset({"other--a", "other--b"}), "location")

    response = client.get("/compare")

    assert "compare-prescreening" not in response.text
    assert "Jev:" not in response.text
    assert "document.addEventListener('keydown'" in response.text
    assert "event.key === 'a'" in response.text
    assert "event.key === 'o'" in response.text
    assert "event.key === 'e'" in response.text


def test_compare_page_rejects_stale_cache_for_just_written_pair(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """If the cached suggestion is exactly the pair that was just written, it must not
    be reused; the next render should fall back to the prescreen flow instead."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    seed_opening(
        conn,
        "widgets--b",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    live_state(client).compare.cache = CompareCache(
        version=0,
        suggestion=ComparisonSuggestion(
            target="location",
            opening_a_id="acme--a",
            opening_b_id="widgets--b",
        ),
        jev_read=RubricVerdict(outcome="tie", confidence=0.62),
    )
    live_state(client).compare.state.version = 1
    live_state(client).compare.state.last_write = (frozenset({"acme--a", "widgets--b"}), "location")

    response = client.get("/compare")

    assert response.status_code == 200
    assert "compare-prescreening" in response.text


def test_compare_review_lists_provisional_comparisons_and_links_to_override(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The review surface shows every un-overridden provisional comparison with a link
    back into the normal compare form for that exact pair/target."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    seed_opening(
        conn,
        "widgets--b",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    append_comparison(
        conn,
        Comparison(
            opening_a_id="acme--a",
            opening_b_id="widgets--b",
            target="location",
            outcome="tie",
            provenance="provisional",
            predicted_a_beats_b=0.5,
            created_at=NOW,
        ),
    )

    response = client.get("/compare/review")

    assert response.status_code == 200
    assert "location" in response.text
    assert "acme--a title" in response.text
    assert "widgets--b title" in response.text
    assert "/compare?opening_a_id=acme--a&opening_b_id=widgets--b&target=location" in response.text


def test_compare_review_shows_empty_state_when_nothing_ruled(
    client: TestClient, db_path: Path
) -> None:
    response = client.get("/compare/review")

    assert response.status_code == 200
    assert "Jev hasn't ruled on anything yet." in response.text


def test_compare_page_display_order_is_not_always_a_on_the_left(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Which opening renders on the left is a deterministic function of the pair and
    dimension, not always the opening passed as `opening_a_id` — so position alone
    doesn't tell the operator which one is "A". Submitting a side's outcome still
    records the correct underlying opening."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("schematic", "Strong", "ratified")],
    )
    seed_opening(
        conn,
        "widgets--b",
        assertions=[canned_assertion("schematic", "Strong", "ratified")],
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

    rows = conn.execute("SELECT outcome FROM comparisons").fetchall()
    assert dict(rows[0])["outcome"] == "b"


def test_compare_page_ruling_edit_redirects_back_to_same_comparison(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Setting an assertion's fit from the compare page redirects back to the same
    comparison (not the rating page's HTMX partial), and the updated fit is reflected
    on reload — the compare page is a primary place rulings get set."""
    assertion = canned_assertion("craft_direction", "Mixed", "ratified")
    seed_opening(
        conn,
        "acme--a",
        assertions=[assertion],
    )
    seed_opening(
        conn,
        "widgets--b",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )

    response = client.post(
        f"/openings/acme--a/assertions/{assertion.id}/ruling",
        data={
            "fit": "Strong",
            "redirect_to": "/compare?opening_a_id=acme--a&opening_b_id=widgets--b&target=craft_direction",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        "/compare?opening_a_id=acme--a&opening_b_id=widgets--b&target=craft_direction"
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
    conn: sqlite3.Connection,
) -> None:
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
    data = {
        "opening_a_id": "acme--a",
        "opening_b_id": "widgets--b",
        "target": "craft_direction",
        "outcome": "a",
    }
    data[field] = value
    response = client.post("/compare", data=data, follow_redirects=False)
    assert response.status_code == expected_status


def test_submit_comparison_rejects_same_opening(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("craft_direction", "Strong", "ratified")],
    )
    response = client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "acme--a",
            "target": "craft_direction",
            "outcome": "a",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("cache_version", "suggestion", "last_write"),
    [
        pytest.param(
            0,
            ComparisonSuggestion(
                target="not_a_dimension", opening_a_id="acme--a", opening_b_id="widgets--b"
            ),
            None,
            id="target no longer in the rubric",
        ),
        pytest.param(
            0,
            ComparisonSuggestion(target="location", opening_a_id="acme--a", opening_b_id="acme--a"),
            None,
            id="pair collapsed onto one opening",
        ),
        pytest.param(
            0,
            ComparisonSuggestion(
                target="location", opening_a_id="acme--a", opening_b_id="ghost--z"
            ),
            None,
            id="opening no longer exists",
        ),
        pytest.param(
            0,
            ComparisonSuggestion(
                target="location", opening_a_id="acme--a", opening_b_id="widgets--b"
            ),
            (frozenset({"other--a", "other--b"}), "location"),
            id="two or more writes behind",
        ),
    ],
)
def test_compare_page_refuses_an_unusable_cached_suggestion(
    client: TestClient,
    db_path: Path,
    cache_version: int,
    suggestion: ComparisonSuggestion,
    last_write: tuple[frozenset[str], str] | None,
    conn: sqlite3.Connection,
) -> None:
    """Each of these cached suggestions is unservable for a different reason — the pair
    is no longer legal, or it is too far behind the live compare state. Serving any of
    them would hand the operator a comparison the current pool can't justify, so the
    route must fall back to the pre-screen flow instead of rendering it."""
    seed_opening(
        conn,
        "acme--a",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    seed_opening(
        conn,
        "widgets--b",
        assertions=[canned_assertion("location", "Strong", "ratified")],
    )
    live_state(client).compare.cache = CompareCache(
        version=cache_version, suggestion=suggestion, jev_read=None
    )
    live_state(client).compare.state.version = cache_version + (1 if last_write is None else 2)
    live_state(client).compare.state.last_write = last_write

    response = client.get("/compare")

    assert response.status_code == 200
    assert "compare-prescreening" in response.text


def test_submitting_a_comparison_serves_the_speculation_without_waiting(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """The throughput claim, end to end: work done while the operator was reading is
    promoted on submit, so the next page renders a comparison instead of the polling
    page. Before speculation existed this GET always hit `just-written-pair` and the
    operator waited out a fresh pool score."""
    for opening_id in (
        "acme--a",
        "widgets--b",
        "gizmo--c",
    ):
        seed_opening(
            conn,
            opening_id,
            assertions=[
                canned_assertion("location", "Strong", "ratified"),
                canned_assertion("schematic", "Strong", "ratified"),
            ],
        )
    judged = (frozenset({"acme--a", "widgets--b"}), "location")
    # A pass is already in flight, so the POST schedules no second one. Under
    # `TestClient` a scheduled task runs to completion before the POST returns, which
    # would overwrite the promoted value and hide whether promotion happened at all.
    live_state(client).compare.progress.running = True
    live_state(client).compare.state.version = 7
    live_state(client).compare.cache = CompareCache(
        version=7,
        suggestion=ComparisonSuggestion(
            target="location", opening_a_id="acme--a", opening_b_id="widgets--b"
        ),
        speculative=ComparisonSuggestion(
            target="schematic", opening_a_id="acme--a", opening_b_id="gizmo--c"
        ),
        speculative_for=judged,
    )

    submitted = client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "location",
            "outcome": "tie",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303

    # Assert on the cache rather than the rendered page: under `TestClient` the POST's
    # background pass runs to completion before this returns, so a fresh (slow) pass
    # would also leave a renderable suggestion here. Only the promoted speculation
    # carries the speculated pair at the stale-by-one version.
    promoted = live_state(client).compare.cache
    assert promoted.suggestion == ComparisonSuggestion(
        target="schematic", opening_a_id="acme--a", opening_b_id="gizmo--c"
    )
    assert promoted.version == 7

    nxt = client.get("/compare")

    assert nxt.status_code == 200
    assert "compare-prescreening" not in nxt.text
    assert '<form class="compare-actions"' in nxt.text
    assert "gizmo--c" in nxt.text


def test_a_speculation_about_a_different_pair_is_not_promoted(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Speculation is computed for one specific on-screen triple. If the operator ends up
    ruling on a different pair (a direct link, a review-surface override), that
    speculation answers a question they were never asked and must not be served as
    their next comparison."""
    for opening_id in (
        "acme--a",
        "widgets--b",
        "gizmo--c",
    ):
        seed_opening(
            conn,
            opening_id,
            assertions=[
                canned_assertion("location", "Strong", "ratified"),
                canned_assertion("schematic", "Strong", "ratified"),
            ],
        )
    live_state(client).compare.progress.running = True
    live_state(client).compare.state.version = 7
    live_state(client).compare.cache = CompareCache(
        version=7,
        suggestion=ComparisonSuggestion(
            target="location", opening_a_id="acme--a", opening_b_id="widgets--b"
        ),
        speculative=ComparisonSuggestion(
            target="schematic", opening_a_id="acme--a", opening_b_id="gizmo--c"
        ),
        speculative_for=(frozenset({"acme--a", "gizmo--c"}), "location"),
    )

    client.post(
        "/compare",
        data={
            "opening_a_id": "acme--a",
            "opening_b_id": "widgets--b",
            "target": "location",
            "outcome": "tie",
        },
        follow_redirects=False,
    )

    assert live_state(client).compare.cache.suggestion != ComparisonSuggestion(
        target="schematic", opening_a_id="acme--a", opening_b_id="gizmo--c"
    )


def test_rerendering_the_same_comparison_does_not_queue_repeated_speculation(
    client: TestClient, db_path: Path, conn: sqlite3.Connection
) -> None:
    """Speculating costs a full pool score. The compare page is re-rendered whenever the
    operator rules an assertion or reloads while deciding, and each render must not
    queue another one for a triple already speculated or in flight."""
    for opening_id in (
        "acme--a",
        "widgets--b",
        "gizmo--c",
    ):
        seed_opening(
            conn,
            opening_id,
            assertions=[
                canned_assertion("location", "Strong", "ratified"),
                canned_assertion("schematic", "Strong", "ratified"),
            ],
        )
    on_screen = ComparisonSuggestion(
        target="location", opening_a_id="acme--a", opening_b_id="widgets--b"
    )
    on_screen_key = (frozenset({"acme--a", "widgets--b"}), "location")
    live_state(client).compare.state.version = 7
    live_state(client).compare.progress.version = 7
    live_state(client).compare.cache = CompareCache(
        version=7,
        suggestion=on_screen,
        speculative=ComparisonSuggestion(
            target="schematic", opening_a_id="acme--a", opening_b_id="gizmo--c"
        ),
        speculative_for=on_screen_key,
    )

    first = client.get("/compare")
    second = client.get("/compare")

    assert first.status_code == 200
    assert second.status_code == 200
    # Untouched: a queued speculation overwrites these on completion.
    assert live_state(client).compare.cache.speculative_for == on_screen_key
    assert live_state(client).compare.speculation_in_flight_for is None
