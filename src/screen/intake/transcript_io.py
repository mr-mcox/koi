"""Wall 6: transcript append-only invariant.

The transcript wrapper exposes `append_line` and `read_transcript`
only, both append-mode (or read). Truncation is not possible through
this module — a future replay command depends on a transcript whose bytes
have not been rewritten since first write.
"""

from collections.abc import Iterator
from pathlib import Path


class TranscriptLockedError(RuntimeError):
    """Raised when a non-append operation is attempted on a non-empty
    transcript file."""


def read_transcript(path: Path) -> Iterator[str]:
    """Yield existing transcript lines one at a time.

    Missing or empty files yield nothing. Each yielded line ends with `\\n`.
    """
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        yield from f


def append_line(path: Path, line: str) -> None:
    """Append a single newline-terminated line to a transcript file.

    First write creates the file. Subsequent writes append. Truncation is
    not possible through this wrapper.
    """
    if not line.endswith("\n"):
        line = line + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
