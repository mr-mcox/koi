"""Tests for the intake queue repo functions."""

from pathlib import Path

from screen.store.db import connect
from screen.store.repo import (
    claim_next_pending_intake_url,
    enqueue_intake_url,
    list_intake_queue,
    mark_intake_url_done,
    mark_intake_url_failed,
)


def test_enqueue_intake_url_survives_reopening_the_connection(tmp_path: Path) -> None:
    """The enqueue write is durable: a fresh connection to the same file still
    sees the row as `pending`, proving it isn't only held in memory."""
    db_path = tmp_path / "screen.db"
    conn = connect(db_path)
    item = enqueue_intake_url(conn, "https://example.com/jobs/1")
    conn.close()

    reopened = connect(db_path)
    items = list_intake_queue(reopened)
    assert [(i.id, i.url, i.status) for i in items] == [(item.id, item.url, "pending")]


def test_claim_next_pending_intake_url_marks_it_running(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    enqueue_intake_url(conn, "https://example.com/jobs/1")

    claimed = claim_next_pending_intake_url(conn)

    assert claimed is not None
    assert claimed.status == "running"
    assert list_intake_queue(conn)[0].status == "running"


def test_claim_next_pending_intake_url_returns_none_when_empty(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    assert claim_next_pending_intake_url(conn) is None


def test_claim_next_pending_intake_url_is_fifo(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    first = enqueue_intake_url(conn, "https://example.com/jobs/1")
    enqueue_intake_url(conn, "https://example.com/jobs/2")

    claimed = claim_next_pending_intake_url(conn)

    assert claimed is not None
    assert claimed.id == first.id


def test_mark_intake_url_done(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    item = enqueue_intake_url(conn, "https://example.com/jobs/1")
    claim_next_pending_intake_url(conn)

    mark_intake_url_done(conn, item.id)

    assert list_intake_queue(conn)[0].status == "done"


def test_mark_intake_url_failed_records_error(tmp_path: Path) -> None:
    conn = connect(tmp_path / "screen.db")
    item = enqueue_intake_url(conn, "https://example.com/jobs/1")
    claim_next_pending_intake_url(conn)

    mark_intake_url_failed(conn, item.id, "fetch: simulated transport failure")

    row = list_intake_queue(conn)[0]
    assert row.status == "failed"
    assert row.error == "fetch: simulated transport failure"
