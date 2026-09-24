"""Integration tests for the web intake-queue surface: enqueue via POST, list
via GET, both against `TestClient`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from screen.api.app import create_app
from screen.digest.fakes import FakeDigester
from screen.store.db import connect
from screen.store.repo import (
    claim_next_pending_intake_url,
    enqueue_intake_url,
    list_intake_queue,
    mark_intake_url_failed,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "screen.db"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    app = create_app(db_path, digester=FakeDigester(["Synthetic digest."]))
    with TestClient(app) as test_client:
        yield test_client


def test_post_intake_queue_enqueues_url_synchronously(client: TestClient, db_path: Path) -> None:
    """The POST returns only after the row is committed — a client that reads the
    DB right after the response sees it, no polling required (bearing: queuing
    itself is blocking)."""
    response = client.post("/intake-queue", data={"url": "https://example.com/jobs/1"})
    assert response.status_code == 200

    conn = connect(db_path)
    items = list_intake_queue(conn)
    assert [i.url for i in items] == ["https://example.com/jobs/1"]


def test_post_intake_queue_rejects_blank_url(client: TestClient, db_path: Path) -> None:
    response = client.post("/intake-queue", data={"url": ""})
    assert response.status_code == 422

    conn = connect(db_path)
    assert list_intake_queue(conn) == []


def test_get_intake_queue_lists_rows_with_status(client: TestClient, db_path: Path) -> None:
    conn = connect(db_path)
    enqueue_intake_url(conn, "https://example.com/jobs/1")
    conn.close()

    response = client.get("/intake-queue")

    assert response.status_code == 200
    assert "https://example.com/jobs/1" in response.text
    assert "pending" in response.text


def test_get_intake_queue_shows_failure_reason_for_failed_rows(
    client: TestClient, db_path: Path
) -> None:
    conn = connect(db_path)
    item = enqueue_intake_url(conn, "https://bad.example/jobs/1")
    claim_next_pending_intake_url(conn)
    mark_intake_url_failed(conn, item.id, "fetch_url: simulated transport failure")
    conn.close()

    response = client.get("/intake-queue")

    assert response.status_code == 200
    assert "failed" in response.text
    assert "simulated transport failure" in response.text


def test_post_retry_requeues_a_failed_row(client: TestClient, db_path: Path) -> None:
    conn = connect(db_path)
    item = enqueue_intake_url(conn, "https://bad.example/jobs/1")
    claim_next_pending_intake_url(conn)
    mark_intake_url_failed(conn, item.id, "fetch_url: simulated transport failure")
    conn.close()

    response = client.post(f"/intake-queue/{item.id}/retry")

    assert response.status_code == 200
    assert "pending" in response.text
    assert "simulated transport failure" not in response.text

    reopened = connect(db_path)
    row = list_intake_queue(reopened)[0]
    assert row.status == "pending"
    assert row.error is None


def test_post_retry_is_a_no_op_on_a_pending_row(client: TestClient, db_path: Path) -> None:
    """Retrying a row that never failed (stale button, double-click) leaves it
    untouched rather than resetting its error/status fields."""
    conn = connect(db_path)
    item = enqueue_intake_url(conn, "https://example.com/jobs/1")
    conn.close()

    response = client.post(f"/intake-queue/{item.id}/retry")

    assert response.status_code == 200
    reopened = connect(db_path)
    assert list_intake_queue(reopened)[0].status == "pending"
