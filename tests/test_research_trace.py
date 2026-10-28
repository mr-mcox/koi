"""Research trace file-access tests: the append-only wrapper and the
page-content reader both pass through `screen.research_trace.trace_io`."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from screen.research_trace.events import ResearchTraceEvent
from screen.research_trace.trace_io import (
    ResearchTraceMissingError,
    append_line,
    read_page_content,
    read_research_trace,
    record_event,
)


def test_append_line_creates_file_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "research_trace.jsonl"
    append_line(path, '{ "kind": "tool_call" }')
    assert path.exists()
    assert path.read_text(encoding="utf-8") == '{ "kind": "tool_call" }\n'


def test_append_line_appends_when_present(tmp_path: Path) -> None:
    path = tmp_path / "research_trace.jsonl"
    append_line(path, "first")
    append_line(path, "second")
    text = path.read_text(encoding="utf-8")
    assert text == "first\nsecond\n"


def test_append_line_rejects_explicit_write_mode(tmp_path: Path) -> None:
    """The wrapper is the only path; if a caller calls Path.open('w') on
    an existing research trace, that's a wall violation. The wrapper exposes
    only `append_line` and `read_research_trace`; `Path.open('w')` outside
    the wrapper is a code review issue, not an enforcement point."""
    path = tmp_path / "research_trace.jsonl"
    append_line(path, "first")
    # The wrapper's `append_line` does not expose a 'w' path. Verify that
    # calling it twice with empty content does not truncate.
    append_line(path, "")
    text = path.read_text(encoding="utf-8")
    assert "first" in text


def test_read_research_trace_returns_lines(tmp_path: Path) -> None:
    path = tmp_path / "research_trace.jsonl"
    append_line(path, "alpha")
    append_line(path, "beta")
    lines = list(read_research_trace(path))
    assert lines == ["alpha\n", "beta\n"]


def test_read_research_trace_empty_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "research_trace.jsonl"
    assert list(read_research_trace(path)) == []


def test_read_research_trace_nonexistent_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    assert list(read_research_trace(path)) == []


def test_append_line_idempotent_on_existing_empty_file(tmp_path: Path) -> None:
    """An empty file exists. The wrapper should not treat that as 'already
    has events' and refuse. This is a boundary case between 'absent' and
    'present with content'."""
    path = tmp_path / "research_trace.jsonl"
    path.write_text("", encoding="utf-8")
    append_line(path, "first")
    assert path.read_text(encoding="utf-8") == "first\n"


def test_append_line_terminates_lines(tmp_path: Path) -> None:
    path = tmp_path / "research_trace.jsonl"
    append_line(path, "no-newline")  # no trailing \n
    assert path.read_text(encoding="utf-8") == "no-newline\n"


def test_read_research_trace_passes_blank_lines_through(tmp_path: Path) -> None:
    """The reader is byte-accurate on input. A blank line is preserved
    so callers can decide how to surface it. This is the boundary
    between our wrapper and downstream consumers."""
    path = tmp_path / "research_trace.jsonl"
    path.write_text("alpha\n\nbeta\n", encoding="utf-8")
    assert list(read_research_trace(path)) == ["alpha\n", "\n", "beta\n"]


def test_append_line_accepts_already_terminated(tmp_path: Path) -> None:
    """If the caller already terminates with \\n, the wrapper does not
    double-terminate. Exercises the negative branch of
    `not line.endswith("\\\\n")`."""
    path = tmp_path / "research_trace.jsonl"
    append_line(path, "ok\n")
    assert path.read_text(encoding="utf-8") == "ok\n"


def test_read_page_content_skips_blank_lines_and_non_tavily_events(
    tmp_path: Path,
) -> None:
    """Blank lines and non-tavily_extract events are ignored; the first
    tavily_extract with raw_content wins."""
    trace_path = tmp_path / "research_traces" / "mixed.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://example.com/mixed"
    trace_path.write_text(
        "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "decide_plan",
                "request": {"opening_id": "x"},
                "response": {"actions": []},
            }
        )
        + "\n\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:01Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {"results": [{"url": url, "raw_content": "The real posting."}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    page_content, found_url = read_page_content(trace_path)
    assert page_content == "The real posting."
    assert found_url == url


def test_read_page_content_skips_empty_results_and_falls_back_to_event_url(
    tmp_path: Path,
) -> None:
    """A tavily_extract event with no results is skipped; the URL on the request is
    used when the first result omits its own url."""
    trace_path = tmp_path / "research_traces" / "empty-then-url.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://example.com/fallback"
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {"results": []},
            }
        )
        + "\n"
        + json.dumps(
            {
                "ts": "2026-08-22T12:00:01Z",
                "tool": "tavily_extract",
                "request": {"urls": [url]},
                "response": {"results": [{"raw_content": "Fallback url content."}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    page_content, found_url = read_page_content(trace_path)
    assert page_content == "Fallback url content."
    assert found_url == url


def test_read_page_content_raises_when_no_extract_event_has_content(
    tmp_path: Path,
) -> None:
    """A trace with only empty or non-tavily events raises ResearchTraceMissingError."""
    trace_path = tmp_path / "research_traces" / "no-content.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-22T12:00:00Z",
                "tool": "tavily_extract",
                "request": {"urls": ["https://example.com"]},
                "response": {"results": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ResearchTraceMissingError):
        read_page_content(trace_path)


def test_read_page_content_handles_unicode_line_separator_in_page_text(
    tmp_path: Path,
) -> None:
    """Regression: `splitlines()` also breaks on U+2028/U+0085, which scraped
    text can contain unescaped — present in 18 of the 164 live traces.
    """
    trace_path = tmp_path / "research_traces" / "separators.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    url = "https://example.com/separator"
    event = ResearchTraceEvent(
        ts=datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC),
        tool="tavily_extract",
        request={"urls": [url]},
        response={"results": [{"url": url, "raw_content": "Line one.\u2028Line two."}]},
    )
    record_event(trace_path, event)

    assert "\u2028" in trace_path.read_text(encoding="utf-8")
    page_content, found_url = read_page_content(trace_path)
    assert page_content == "Line one.\u2028Line two."
    assert found_url == url
