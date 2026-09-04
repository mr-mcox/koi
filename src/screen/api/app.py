"""FastAPI app for serving scores and the ranked queue.

`Database` is the connection-lifecycle seam: it knows where the SQLite file lives
and how to open a connection with foreign keys enabled and migrations applied.
`repo.py` remains a flat module of SQL operations that accept a `sqlite3.Connection`;
this keeps the two concerns separate.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI

from screen.api.routes import router as api_router
from screen.digest.baml_digester import BAMLDigester
from screen.digest.protocol import DigesterProtocol
from screen.paths import data_dir
from screen.research.batch import BatchEngine
from screen.store.db import connect as db_connect
from screen.web.routes import router as web_router
from screen.web.routes import static_files


class Database:
    """Connection factory. Today it opens a SQLite file per call; the only
    persistence-seam the API needs to swap for a hosted or pooled backend later."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @property
    def data_root(self) -> Path:
        """Research traces and other per-data-root files live next to the DB."""
        return self.db_path.parent

    def connect(self) -> sqlite3.Connection:
        return db_connect(self.db_path)

    @classmethod
    def default(cls) -> Database:
        return cls(data_dir() / "screen.db")


def create_app(db_path: Path | None = None, digester: DigesterProtocol | None = None) -> FastAPI:
    """Application factory. Tests pass a temp path; production uses the default.
    `app.state.database` is what `screen.api.deps.get_db` reads per request.
    `app.state.digester` is the `DigesterProtocol` the web rating view uses for
    dimension digests; tests inject a fake, production gets the BAML adapter."""
    database = Database(db_path) if db_path else Database.default()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Ensure the DB file and migrations exist before serving traffic."""
        conn = database.connect()
        conn.close()
        yield

    app = FastAPI(title="screen", lifespan=lifespan)
    app.state.database = database
    app.state.digester = digester if digester is not None else BAMLDigester()
    app.state.batch_engine = BatchEngine()
    app.state.batch_status = {
        "running": False,
        "total": 0,
        "spent": 0,
        "current_opening_id": None,
        "touched": [],
    }
    app.include_router(web_router)
    app.include_router(api_router)
    app.mount("/static", static_files, name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# Production module-level app for `uvicorn screen.api.app:app`.
app = create_app()
