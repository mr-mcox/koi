"""Tests for render_assertion_history — the shared renderer giving the
Surveyor and Navigator what a dimension's assertions actually say, not just
how many there are."""

from screen.research.question import render_assertion_history
from tests.helpers import canned_assertion, canned_citation


def test_unexamined_dimension_renders_explicitly() -> None:
    rendered = render_assertion_history([], ["craft_direction"])

    assert "craft_direction" in rendered
    assert "unexamined" in rendered


def test_examined_dimension_renders_fit_chunk_and_citation_url() -> None:
    assertion = canned_assertion(
        target="compensation",
        fit="Strong",
        chunk="Staff engineers earn $380k-$450k TC.",
        citations=[canned_citation(url="https://levels.fyi/acme")],
    )

    rendered = render_assertion_history([assertion], ["compensation"])

    assert "compensation" in rendered
    assert "Strong" in rendered
    assert "Staff engineers earn $380k-$450k TC." in rendered
    assert "https://levels.fyi/acme" in rendered
    assert "unexamined" not in rendered


def test_multiple_assertions_for_one_target_each_render() -> None:
    first = canned_assertion(target="mission", chunk="First claim.")
    second = canned_assertion(target="mission", chunk="Second claim.")

    rendered = render_assertion_history([first, second], ["mission"])

    assert "First claim." in rendered
    assert "Second claim." in rendered


def test_targets_render_in_the_given_order_not_assertion_order() -> None:
    mission_claim = canned_assertion(target="mission", chunk="Mission claim.")

    rendered = render_assertion_history([mission_claim], ["compensation", "mission"])

    assert rendered.index("compensation") < rendered.index("mission")


def test_assertion_for_target_outside_the_given_list_is_excluded() -> None:
    off_target = canned_assertion(target="location", chunk="Should not appear.")

    rendered = render_assertion_history([off_target], ["compensation"])

    assert "Should not appear." not in rendered
    assert "location" not in rendered


def test_duplicate_citation_urls_on_one_assertion_collapse() -> None:
    assertion = canned_assertion(
        target="domain",
        citations=[
            canned_citation(url="https://example.com/a"),
            canned_citation(url="https://example.com/a"),
        ],
    )

    rendered = render_assertion_history([assertion], ["domain"])

    assert rendered.count("https://example.com/a") == 1
