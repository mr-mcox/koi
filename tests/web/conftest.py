"""Fixtures for the review-surface tests."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from screen.digest.fakes import FakeDigester
from screen.store.db import connect
from screen.verdict.protocol import FewShotExample, RubricVerdict
from tests.helpers import make_app


class _NeverConfidentVerdictProvider:
    """Always returns a verdict below any sane confidence threshold, so the comparison
    pre-screen pass is always a no-op. The default for `client`/`db_path`-based tests,
    which exercise the `/compare` flow without caring about the pre-screen kernel at all;
    never calls the real (networked, paid) Jev API."""

    def rule(
        self,
        rubric_text: str,
        digest_a: str,
        digest_b: str,
        few_shot_examples: list[FewShotExample],
    ) -> RubricVerdict:
        return RubricVerdict(outcome="tie", confidence=0.0)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "screen.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    yield conn
    conn.close()


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    """A TestClient backed by a fresh database at a temporary path. The verdict-provider
    fake guarantees the comparison pre-screen pass is always a no-op, so these tests
    exercise `/compare` exactly as before the pre-screen kernel existed;
    `tests/test_pool_store.py` and `tests/compare/test_prescreen.py` cover the kernel
    itself."""
    app = make_app(
        db_path,
        digester=FakeDigester(["Synthetic digest."]),
        verdict_provider=_NeverConfidentVerdictProvider(),
    )
    with TestClient(app) as test_client:
        yield test_client
