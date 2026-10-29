"""Loads the repo-root `.env` into the process environment.

Called once at app startup. Secrets (`TYPESAFE_API_KEY`, `TAVILY_API_KEY`) live in the
gitignored `.env`. An already-set variable always wins — exporting a key in the shell is
a deliberate per-run override.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _REPO_ROOT / ".env"


def load_env(
    env_path: Path = _ENV_PATH,
    environ: dict[str, str] | None = None,
) -> None:
    """Populate `environ` with any key in `env_path` that isn't already set. A missing
    file is a no-op — agent sessions and CI legitimately have no `.env`."""
    target = environ if environ is not None else os.environ
    if not env_path.is_file():
        return
    for key, value in dotenv_values(env_path).items():
        if value is not None and key not in target:
            target[key] = value
