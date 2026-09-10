"""Opens the SQLite file, applying pending migrations before returning it.

The one seam between `screen.store` and the filesystem — `migrate.py` and
`mappers.py` stay filesystem-agnostic so they're testable against
`:memory:` connections directly.
"""

import sqlite3
from pathlib import Path

from screen.store.migrate import apply_migrations

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    """`check_same_thread=False`: FastAPI dispatches a sync-generator dependency's
    pre-yield and post-yield halves via separate thread-pool calls, so a
    request's connection can be created on one OS thread and closed on
    another — sqlite3's default thread-affinity check rejects that even
    though only one request ever touches the connection at a time."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn, _MIGRATIONS_DIR)
    return conn
