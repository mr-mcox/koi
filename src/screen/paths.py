"""Shared data-root seam. `SCREEN_DATA_DIR` selects where the app reads and writes
the DB and the research trace files."""

from collections.abc import Mapping
from pathlib import Path


def data_dir(environ: Mapping[str, str]) -> Path:
    env = environ.get("SCREEN_DATA_DIR")
    return Path(env).resolve() if env else Path("data").resolve()
