"""Renders a plain-text digest into structured HTML for the rating view.

The digest prompt (`digest.baml`) is constrained to plain prose, optional line
breaks, and leading-dash bullet lines — no markdown parser dependency is
justified for that small a grammar (Not Doing, digest-latency-and-style).
Digest text is operator-facing but LLM-authored, so it is always escaped;
this module is the only place a digest's structure becomes tags.
"""

from __future__ import annotations

from itertools import groupby

from markupsafe import Markup, escape


def _is_bullet(line: str) -> bool:
    return line.startswith("- ")


def _render_run(is_bullet: bool, lines: list[str]) -> str:
    if is_bullet:
        items = "".join(f"<li>{escape(line[2:])}</li>" for line in lines)
        return f"<ul>{items}</ul>"
    return "<br>".join(str(escape(line)) for line in lines)


def render_digest_html(digest: str) -> Markup:
    """Convert line breaks and leading-dash bullets into `<br>` / `<ul><li>`.

    Consecutive bullet lines (starting with "- ") become one `<ul>`; consecutive
    non-bullet lines join with `<br>`. Blank lines are dropped. All text
    content is escaped.
    """
    non_blank = [line for line in digest.split("\n") if line != ""]
    rendered = "".join(
        _render_run(is_bullet, list(group)) for is_bullet, group in groupby(non_blank, _is_bullet)
    )
    return Markup(rendered)
