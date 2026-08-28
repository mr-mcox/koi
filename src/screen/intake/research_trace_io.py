"""Append-only wrapper for the research trace file.

This is an interim resumability substrate, not the evidence ledger — see
docs/architecture/decisions.md E5 for the ratified `ResearchPass` contract.
The wrapper exposes `append_line` and `read_research_trace` only, both
append-mode (or read); truncation is not possible through this module.
"""

from collections.abc import Iterator
from pathlib import Path


class ResearchTraceLockedError(RuntimeError):
    """Raised when a non-append operation is attempted on a non-empty
    research trace file."""


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
