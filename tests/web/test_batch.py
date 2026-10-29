"""Integration tests for starting and polling a research batch."""

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screen.digest.fakes import FakeDigester
from screen.extract.fakes import FakeExtractor
from screen.research.actions import SearchAction, StopAction
from screen.research.batch import BatchEngine
from screen.research.fakes import FakeBrowser
from screen.research_trace.replay import replay_research_trace
from screen.research_trace.trace_io import research_trace_path_for
from screen.store.db import connect
from screen.store.repo import (
    get_opening,
)
from tests.helpers import (
    canned_assertion,
    fake_dispatch_deps,
    make_app,
    seed_opening,
    seed_research_trace,
)

_LIVE_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _seed_research_trace(data_root: Path, opening_id: str) -> None:
    """Write a minimal research trace so the batch engine can resume the opening."""
    seed_research_trace(
        research_trace_path_for(data_root, f"tx-{opening_id}"),
        f"Posting for {opening_id}.",
        f"https://example.com/{opening_id}",
    )


def _seed_live_opening(db_path: Path, opening_id: str) -> None:
    conn = connect(db_path)
    seed_opening(conn, opening_id, created_at=_LIVE_NOW)
    conn.close()
    _seed_research_trace(db_path.parent, opening_id)


@contextlib.contextmanager
def _live_server(app: FastAPI) -> Iterator[str]:
    """Run `app` in a uvicorn thread and yield its base URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=1)
        raise RuntimeError("live server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=2)


class PausablePlanner:
    """Fake planner that blocks on the first `plan()` call until `gate` is set,
    then returns one `SearchAction` and stops on subsequent calls."""

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self._called = 0

    def plan(self, _state: object) -> list:
        self._called += 1
        if self._called == 1:
            self._gate.wait()
            return [SearchAction(query="paused query")]
        return [StopAction(reason="done")]


def _pausable_engine(gate: threading.Event) -> BatchEngine:
    """Engine whose first-turn planner blocks on `gate`, then spends one fake turn."""
    shared_planner = PausablePlanner(gate)
    return BatchEngine(
        planner_factory=lambda: shared_planner,
        deps_factory=lambda: fake_dispatch_deps(
            browser=FakeBrowser(search_fixtures={"paused query": []}),
            extractor=FakeExtractor([[canned_assertion("craft_direction", "Strong", "ratified")]]),
            digester=FakeDigester(["Synthetic digest."]),
        ),
    )


def test_batch_start_returns_before_turn_is_spent(db_path: Path) -> None:
    """POST /batch schedules the work in a background task and returns immediately,
    before the slow planner even finishes its first `plan()` call."""
    _seed_live_opening(db_path, "acme--eng")
    gate = threading.Event()
    app = make_app(
        db_path, digester=FakeDigester(["Synthetic digest."]), batch_engine=_pausable_engine(gate)
    )

    with _live_server(app) as base, httpx.Client() as client:
        t0 = time.time()
        response = client.post(f"{base}/batch", data={"batch_size": "3"})
        t1 = time.time()
        assert response.status_code == 200, response.text
        assert "Researching" in response.text
        # The response must land before the gate is released.
        assert t1 - t0 < 0.5

        # Poll the status endpoint while the batch is still blocked.
        for _ in range(50):
            status = client.get(f"{base}/batch-status")
            assert status.status_code == 200
            if "Researching" in status.text:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("batch did not show running status")

        # Now let the background task finish its first (and only) turn.
        gate.set()
        for _ in range(50):
            status = client.get(f"{base}/batch-status")
            if "Researching" not in status.text:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("batch never finished")
        assert "Researching" not in status.text

        # One turn was actually spent (2 turns total: 1 seeded + 1 from the batch).
        conn = connect(db_path)
        opening = get_opening(conn, "acme--eng")
        assert opening is not None
        trace_path = research_trace_path_for(db_path.parent, opening.research_trace_id)
        used = replay_research_trace(trace_path).turns_used
        conn.close()
        assert used == 2


def test_second_batch_start_is_rejected_while_one_is_running(db_path: Path) -> None:
    """Two rapid POST /batch requests only run one batch; the second gets a clear error."""
    _seed_live_opening(db_path, "acme--eng")
    _seed_live_opening(db_path, "widgets--eng")
    gate = threading.Event()
    app = make_app(
        db_path, digester=FakeDigester(["Synthetic digest."]), batch_engine=_pausable_engine(gate)
    )

    with _live_server(app) as base, httpx.Client() as client:
        first = client.post(f"{base}/batch", data={"batch_size": "3"})
        assert first.status_code == 200
        assert "Researching" in first.text

        second = client.post(f"{base}/batch", data={"batch_size": "3"})
        assert second.status_code == 200
        assert "already running" in second.text

        gate.set()


def test_batch_start_form_validates_batch_size(client: TestClient) -> None:
    """The batch start form rejects non-positive batch sizes."""
    response = client.post("/batch", data={"batch_size": "0"})
    assert response.status_code == 422


def test_batch_start_defaults_to_50_turns_when_omitted(client: TestClient) -> None:
    """The queue page's single start button posts no visible batch_size; the server
    defaults to 50 turns (queue-page-cleanup bearing, Done When)."""
    response = client.post("/batch", data={})
    assert response.status_code == 200
    assert "Researching" in response.text


def test_queue_hides_research_turns_used_and_budget(client: TestClient, db_path: Path) -> None:
    """Queue rows no longer show the turns-used/budget counter (queue-page-cleanup
    bearing, Done When)."""
    _seed_live_opening(db_path, "acme--eng")
    response = client.get("/")
    assert response.status_code == 200
    assert "research-status" not in response.text
    assert "1/5" not in response.text
