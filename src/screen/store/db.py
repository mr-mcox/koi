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
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn, _MIGRATIONS_DIR)
    return conn
