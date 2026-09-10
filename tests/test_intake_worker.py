"""Unit tests for the intake-queue worker.

Tests drive `process_next_intake_url` directly — the unit that claims one
row, runs the pipeline, and records the outcome. The always-running loop
around it (`run_intake_worker`) is a thin `asyncio.sleep`-when-idle wrapper
with nothing of its own worth unit-testing beyond that it calls this.
"""

from __future__ import annotations

import asyncio
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
