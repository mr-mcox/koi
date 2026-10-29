"""FastAPI app for serving scores and the ranked queue.

`Database` is the connection-lifecycle seam: it knows where the SQLite file lives
and how to open a connection with foreign keys enabled and migrations applied.
`repo.py` remains a flat module of SQL operations that accept a `sqlite3.Connection`;
this keeps the two concerns separate.

`create_app` takes every external collaborator as an `AppDeps`; the production app is
assembled in `screen.wiring` and served from `screen.api.main`.
"""

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI

from screen.api.routes import router as api_router
from screen.compare.session import CompareSession
from screen.digest.protocol import Digester
from screen.extract.prompt import RubricText
from screen.intake.worker import run_intake_worker
from screen.research.batch import BatchEngine, BatchProgress
from screen.store.db import connect as db_connect
from screen.verdict.protocol import VerdictProvider
from screen.web.common import static_files
from screen.web.routes import router as web_router


class Database:
    """Connection factory: opens the SQLite file once per call. The one persistence seam
    a hosted or pooled backend would replace."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        return db_connect(self.db_path)


@dataclass(frozen=True)
class AppDeps:
    """The app's external collaborators. `intake_fn` runs the intake pipeline for one
    queued URL; the lifespan worker calls it for every row."""

    rubric: RubricText
    digester: Digester
    verdict_provider: VerdictProvider
    batch_engine: BatchEngine
    intake_fn: Callable[[str], str]


@dataclass
class AppState:
    """The app's mutable in-process state, shared between request handlers and the
    background tasks they schedule. Single-uvicorn-worker assumption; not persisted."""

    batch: BatchProgress = field(default_factory=BatchProgress)
    compare: CompareSession = field(default_factory=CompareSession)


def _enable_compare_instrumentation() -> None:
    """Make the compare-throughput loggers visible under uvicorn, which configures only
    its own loggers. Without a handler these records are swallowed, and the live session
    this instrumentation exists to measure would show nothing."""
    for name in ("screen.compare", "screen.prescreen"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
            logger.addHandler(handler)
        logger.propagate = False


def create_app(database: Database, deps: AppDeps) -> FastAPI:
    """Application factory. `app.state.database` is what `screen.api.deps.get_db` reads
    per request; `app.state.deps` and `app.state.live` are what `screen.api.deps.app_deps`
    and `screen.api.deps.app_state` read."""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Ensure the DB file and migrations exist before serving traffic, then
        start the intake-queue worker on its own connection for the life of
        the app — it must keep running across many requests, unlike the
        research batch's per-submission `BackgroundTasks` job."""
        conn = database.connect()
        worker_conn = database.connect()
        worker_task = asyncio.create_task(run_intake_worker(worker_conn, deps.intake_fn))
        conn.close()
        yield
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        worker_conn.close()

    app = FastAPI(title="screen", lifespan=lifespan)
    app.state.database = database
    app.state.deps = deps
    app.state.live = AppState()
    _enable_compare_instrumentation()
    app.include_router(web_router)
    app.include_router(api_router)
    app.mount("/static", static_files, name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
