"""Web intake-queue worker.

`process_next_intake_url` claims and processes one pending row; the queue's
durable, blocking-write enqueue lives in `store/repo.py`
(`enqueue_intake_url`). `run_intake_worker` is the always-on loop the FastAPI
lifespan starts once, so a row added mid-run is picked up without a restart —
it just calls `process_next_intake_url` again.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from pathlib import Path

from screen.intake.pipeline import intake_url
from screen.store.repo import (
    claim_next_pending_intake_url,
    mark_intake_url_done,
    mark_intake_url_failed,
)
from screen.types import IntakeQueueItem

_IDLE_POLL_SECONDS = 2.0


def process_next_intake_url(
    conn: sqlite3.Connection,
    _data_dir: Path,
    *,
    intake_fn: Callable[[str], str] | None = None,
) -> IntakeQueueItem | None:
    """Claim the oldest pending row and run `intake_fn` on its URL. Any
    failure — `IntakePipelineError` or otherwise, since a later pipeline
    stage (BAML, extraction) can raise its own exception shape — is recorded
    on the row rather than propagated, so one bad URL never stops the queue
    (bearing: skip-and-continue). Returns `None` if the queue was empty.

    `intake_fn` defaults to this module's `intake_url` reference, resolved at
    call time (not bound as a default argument) so tests can monkeypatch it.
    """
    item = claim_next_pending_intake_url(conn)
    if item is None:
        return None
    fn = intake_fn if intake_fn is not None else intake_url
    try:
        fn(item.url)
    except (
        Exception
    ) as exc:  # deliberately broad: recorded per-row, never re-raised (skip-and-continue)
        mark_intake_url_failed(conn, item.id, str(exc))
        return item.model_copy(update={"status": "failed", "error": str(exc)})
    mark_intake_url_done(conn, item.id)
    return item.model_copy(update={"status": "done"})


async def run_intake_worker(conn: sqlite3.Connection, data_dir: Path) -> None:
    """Runs for the life of the process (started once from the FastAPI
    lifespan). Polls at `_IDLE_POLL_SECONDS` when the queue is empty; drains
    immediately, one row at a time, while work is pending."""
    while True:
        item = process_next_intake_url(conn, data_dir)
        if item is None:
            await asyncio.sleep(_IDLE_POLL_SECONDS)
