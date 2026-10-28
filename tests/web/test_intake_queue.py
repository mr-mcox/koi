"""Integration tests for the web intake-queue surface: enqueue via POST, list
via GET, both against `TestClient`."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from screen.intake.admission import DECLINED_HOSTS
from screen.store.db import connect
from screen.store.repo import (
    claim_next_pending_intake_url,
    enqueue_intake_url,
    list_intake_queue,
    mark_intake_url_failed,
)


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


def test_post_intake_queue_refuses_a_declined_host_without_queuing(
    client: TestClient, db_path: Path
) -> None:
    """No row, no worker pass, no Retry button that could never succeed."""
    declined_host = DECLINED_HOSTS[0]

    response = client.post(
        "/intake-queue", data={"url": f"https://{declined_host}/job/some-posting"}
    )

    assert response.status_code == 200
    assert "declines automated access" in response.text

    conn = connect(db_path)
    assert list_intake_queue(conn) == []


def test_post_intake_queue_refusal_names_the_substitute_link(client: TestClient) -> None:
    """A refusal that only says no relocates the dead end instead of
    clearing it — the employer's own ATS has the same job, two clicks away.
    """
    response = client.post(
        "/intake-queue", data={"url": f"https://{DECLINED_HOSTS[0]}/job/some-posting"}
    )

    assert "Greenhouse" in response.text


def test_post_intake_queue_still_accepts_an_ordinary_host(
    client: TestClient, db_path: Path
) -> None:
    """The decline list is a named exception, not a posture."""
    response = client.post("/intake-queue", data={"url": "https://example.com/jobs/1"})

    assert response.status_code == 200
    assert "declines automated access" not in response.text

    conn = connect(db_path)
    assert [i.url for i in list_intake_queue(conn)] == ["https://example.com/jobs/1"]
