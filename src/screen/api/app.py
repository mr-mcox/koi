"""FastAPI app for serving scores and the ranked queue.

`Database` is the connection-lifecycle seam: it knows where the SQLite file lives
and how to open a connection with foreign keys enabled and migrations applied.
`repo.py` remains a flat module of SQL operations that accept a `sqlite3.Connection`;
this keeps the two concerns separate.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI

from screen.api.routes import router
from screen.store.db import connect as db_connect


def _data_dir() -> Path:
    env = os.environ.get("SCREEN_DATA_DIR")
    return Path(env).resolve() if env else Path("data").resolve()


class Database:
    """Connection factory. Today it opens a SQLite file per call; the only
    persistence-seam the API needs to swap for a hosted or pooled backend later."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        return db_connect(self.db_path)

    @classmethod
    def default(cls) -> Database:
        return cls(_data_dir() / "screen.db")


def create_app(db_path: Path | None = None) -> FastAPI:
    """Application factory. Tests pass a temp path; production uses the default.
    `app.state.database` is what `screen.api.deps.get_db` reads per request."""
    database = Database(db_path) if db_path else Database.default()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Ensure the DB file and migrations exist before serving traffic."""
        conn = database.connect()
        conn.close()
        yield

    app = FastAPI(title="screen", lifespan=lifespan)
    app.state.database = database
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# Production module-level app for `uvicorn screen.api.app:app`.
app = create_app()
