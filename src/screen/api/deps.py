"""FastAPI dependency for a per-request SQLite connection.

`get_db` reads the `Database` instance off `request.app.state` rather than
being rebuilt per app instance — this keeps it a fixed function reference,
so route signatures can use a plain module-level `Annotated` type alias.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

from fastapi import Request


def get_db(request: Request) -> Generator[sqlite3.Connection]:
    """One connection per request. The only seam a hosted/pooled backend would
    need to replace — routes only ever see a `sqlite3.Connection`."""
    conn = request.app.state.database.connect()
    try:
        yield conn
    finally:
        conn.close()
