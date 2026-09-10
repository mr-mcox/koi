"""Unit tests for the intake-queue worker.

Tests drive `process_next_intake_url` directly — the unit that claims one
row, runs the pipeline, and records the outcome. The always-running loop
around it (`run_intake_worker`) is a thin `asyncio.sleep`-when-idle wrapper
with nothing of its own worth unit-testing beyond that it calls this.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

import screen.intake.worker as worker_module
from screen.intake.pipeline import IntakePipelineError
from screen.intake.worker import process_next_intake_url, run_intake_worker
from screen.store.db import connect
from screen.store.repo import enqueue_intake_url, list_intake_queue


def test_process_next_intake_url_returns_none_when_queue_empty(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    assert process_next_intake_url(conn, tmp_path, intake_fn=lambda url: "unused") is None


def test_process_next_intake_url_marks_success_as_done(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")

    item = process_next_intake_url(conn, tmp_path, intake_fn=lambda url: "stopped: done")

    assert item is not None
    assert item.status == "done"
    assert list_intake_queue(conn)[0].status == "done"


def test_process_next_intake_url_marks_failure_and_records_stage(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")

    def _fail(url: str) -> str:
        raise IntakePipelineError("fetch_url", "simulated transport failure")

    item = process_next_intake_url(conn, tmp_path, intake_fn=_fail)

    assert item is not None
    assert item.status == "failed"
    row = list_intake_queue(conn)[0]
    assert row.status == "failed"
    assert row.error == "fetch_url: simulated transport failure"


def test_process_next_intake_url_catches_any_exception_not_just_pipeline_error(
    tmp_path: Path,
) -> None:
    """A non-`IntakePipelineError` failure (e.g. a BAML/pydantic error from a later
    stage) still lands as `failed`, not an unhandled exception that would kill the
    worker loop (checkpoint: skip-and-continue must survive any failure shape)."""
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")

    def _fail(url: str) -> str:
        raise ValueError("unexpected shape from a later stage")

    item = process_next_intake_url(conn, tmp_path, intake_fn=_fail)

    assert item is not None
    assert item.status == "failed"
    assert "unexpected shape from a later stage" in (item.error or "")


def test_process_next_intake_url_continues_after_a_failure(tmp_path: Path) -> None:
    """One failed URL doesn't block the next pending one — two calls in
    sequence process both rows to distinct terminal states."""
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://bad.example/jobs/1")
    enqueue_intake_url(conn, "https://good.example/jobs/2")

    def _intake_fn(url: str) -> str:
        if "bad" in url:
            raise IntakePipelineError("fetch_url", "simulated failure")
        return "stopped: done"

    first = process_next_intake_url(conn, tmp_path, intake_fn=_intake_fn)
    second = process_next_intake_url(conn, tmp_path, intake_fn=_intake_fn)

    assert first is not None and first.status == "failed"
    assert second is not None and second.status == "done"


def test_process_next_intake_url_picks_up_a_row_enqueued_mid_processing(
    tmp_path: Path,
) -> None:
    """A URL enqueued while the first item is being processed is picked up by
    the next call — no worker restart needed, matching the bearing's
    append-while-running commitment."""
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")

    def _intake_fn(url: str) -> str:
        enqueue_intake_url(conn, "https://example.com/jobs/2")
        return "stopped: done"

    first = process_next_intake_url(conn, tmp_path, intake_fn=_intake_fn)
    second = process_next_intake_url(conn, tmp_path, intake_fn=lambda url: "stopped: done")

    assert first is not None and first.url == "https://example.com/jobs/1"
    assert second is not None and second.url == "https://example.com/jobs/2"
    assert {row.status for row in list_intake_queue(conn)} == {"done"}


def test_process_next_intake_url_uses_intake_url_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no `intake_fn` override, the real pipeline entry point is called."""
    calls: list[str] = []
    monkeypatch.setattr(worker_module, "intake_url", lambda url: calls.append(url) or "done")
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")

    process_next_intake_url(conn, tmp_path)

    assert calls == ["https://example.com/jobs/1"]


async def test_run_intake_worker_drains_then_polls_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop drains every pending row without sleeping, then sleeps once the
    queue is empty — both branches of the idle check exercised in one run."""
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")
    enqueue_intake_url(conn, "https://example.com/jobs/2")
    monkeypatch.setattr(worker_module, "intake_url", lambda url: "stopped: done")

    sleep_calls = 0

    async def _fake_sleep(seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        raise asyncio.CancelledError

    monkeypatch.setattr(worker_module.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await run_intake_worker(conn, tmp_path)

    assert sleep_calls == 1
    assert {row.status for row in list_intake_queue(conn)} == {"done"}


async def test_run_intake_worker_does_not_block_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow, blocking `intake_fn` (real network + DB I/O, not an awaitable) must
    not freeze the event loop — other coroutines (e.g. FastAPI serving a
    concurrent request) need to keep making progress while one URL is in
    flight. Simulates the blocking call with `time.sleep`; if the worker calls
    it directly (not via a thread), the loop is frozen for its whole duration
    and the ticker below can't record a tick until it's over."""
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")
    block_seconds = 0.3

    def _slow_intake_fn(url: str) -> str:
        time.sleep(block_seconds)
        return "stopped: done"

    monkeypatch.setattr(worker_module, "intake_url", _slow_intake_fn)

    tick_times: list[float] = []

    async def _ticker() -> None:
        while True:
            tick_times.append(asyncio.get_running_loop().time())
            await asyncio.sleep(0.01)

    loop = asyncio.get_running_loop()
    start = loop.time()
    ticker_task = asyncio.create_task(_ticker())
    worker_task = asyncio.create_task(run_intake_worker(conn, tmp_path))
    await asyncio.sleep(block_seconds * 1.5)  # outlasts the blocking call
    worker_task.cancel()
    ticker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker_task
    with pytest.raises(asyncio.CancelledError):
        await ticker_task

    assert any(
        t - start < block_seconds / 2 for t in tick_times[1:]
    ), "the event loop was blocked for the whole duration of the synchronous intake call"
    assert list_intake_queue(conn)[0].status == "done"
