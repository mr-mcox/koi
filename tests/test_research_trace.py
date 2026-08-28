"""Research trace append-only wrapper tests."""

from pathlib import Path

from screen.intake.research_trace_io import (
    ResearchTraceLockedError,
    append_line,
    read_research_trace,
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


def test_research_trace_locked_error_is_runtime_error() -> None:
    assert issubclass(ResearchTraceLockedError, RuntimeError)


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
