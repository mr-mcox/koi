"""Append-only file access for the research trace.
This is an interim resumability substrate, not the evidence ledger — see
docs/architecture/decisions.md E5 for the ratified `ResearchPass` contract.
Every write goes through `append_line`; truncation is not possible through
this module.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import cast

from screen.research_trace.events import ResearchTraceEvent, TavilyExtractResponse


class ResearchTraceMissingError(RuntimeError):
    """Raised when an opening's research trace file is missing or has no
    tavily_extract event with raw_content."""


def research_trace_path_for(data_root: Path, research_trace_id: str) -> Path:
    return data_root / "research_traces" / f"{research_trace_id}.jsonl"


def record_event(research_trace_path: Path, event: ResearchTraceEvent) -> None:
    append_line(research_trace_path, event.model_dump_json())


def read_page_content(research_trace_path: Path) -> tuple[str, str]:
    """Return (raw_content, url) from the first tavily_extract event."""
    if not research_trace_path.exists():
        raise ResearchTraceMissingError(f"research trace missing at {research_trace_path}")
    # `split`, not `splitlines`: the latter also breaks on U+2028 and kin,
    # which scraped text contains and `model_dump_json` leaves unescaped.
    for raw_line in research_trace_path.read_text(encoding="utf-8").split("\n"):
        if not raw_line:
            continue
        event = ResearchTraceEvent.model_validate_json(raw_line)
        if event.tool != "tavily_extract":
            continue
        response = cast(TavilyExtractResponse, event.response)
        results = response.get("results") or []
        if not results:
            continue
        first = results[0]
        url = first.get("url") or (event.request.get("urls") or [""])[0]
        raw_content = first.get("raw_content", "")
        return str(raw_content), str(url)
    raise ResearchTraceMissingError(
        f"no tavily_extract event with raw_content in {research_trace_path}"
    )


def read_research_trace(path: Path) -> Iterator[str]:
    """Yield existing research trace lines one at a time.

    Missing or empty files yield nothing. Each yielded line ends with `\\n`.
    """
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        yield from f


def append_line(path: Path, line: str) -> None:
    """Append a single newline-terminated line to a research trace file.

    First write creates the file. Subsequent writes append. Truncation is
    not possible through this wrapper.
    """
    if not line.endswith("\n"):
        line = line + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
