"""Tests for `render_digest_html` — converts a plain-text digest (line breaks
and leading-dash bullets, the only formatting the digest prompt is allowed to
produce) into safe, structured HTML for the rating view template."""

from __future__ import annotations

from screen.digest.render import render_digest_html


def test_plain_sentence_is_escaped_and_unwrapped() -> None:
    """A single-line digest with no bullets renders as escaped text, no wrapper tags."""
    result = render_digest_html("High-bar culture, some tension on process.")
    assert result == "High-bar culture, some tension on process."


def test_html_in_digest_text_is_escaped() -> None:
    """Digest text is never trusted as HTML — angle brackets and entities are escaped."""
    result = render_digest_html("Team says <b>fast-moving</b> & blunt.")
    assert "<b>" not in result
    assert "&lt;b&gt;" in result
    assert "&amp;" in result


def test_multiple_plain_lines_join_with_br() -> None:
    """Non-bullet lines join with `<br>`, preserving the line breaks the digest returned."""
    result = render_digest_html("First point.\nSecond point.")
    assert result == "First point.<br>Second point."


def test_leading_dash_lines_render_as_bullet_list() -> None:
    """Lines starting with '- ' render as a `<ul><li>` list."""
    result = render_digest_html("- Autonomy is real.\n- Process is heavy.")
    assert result == "<ul><li>Autonomy is real.</li><li>Process is heavy.</li></ul>"


def test_mixed_prose_and_bullets_renders_both_in_order() -> None:
    """A leading prose line followed by bullets renders the prose, then the list."""
    result = render_digest_html("Evidence is mixed:\n- Autonomy is real.\n- Process is heavy.")
    assert result == (
        "Evidence is mixed:<ul><li>Autonomy is real.</li><li>Process is heavy.</li></ul>"
    )


def test_empty_digest_renders_empty_string() -> None:
    """An empty digest (should not happen, but no crash) renders as empty."""
    assert render_digest_html("") == ""
