"""Applies numbered .sql migration files to a SQLite connection.

Each file runs once, tracked in `schema_migrations`. Files are applied in
filename-sorted order — the numeric prefix (0001_, 0002_, ...) is the
ordering contract, not a convention worth re-deriving from content.
"""

import sqlite3
from pathlib import Path

_TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    conn.execute(_TRACKING_TABLE_SQL)
    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations").fetchall()}
    pending = sorted(p for p in migrations_dir.glob("*.sql") if p.name not in applied)
    for path in pending:
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
    conn.commit()
