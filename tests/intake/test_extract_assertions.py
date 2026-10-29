"""Unit tests for `extract_and_persist_assertions` — extract-and-persist, called directly."""

from pathlib import Path

from screen.extract.fakes import FakeExtractor
from screen.intake.pipeline import extract_and_persist_assertions
from screen.store.db import connect
from screen.store.repo import assertions_for_opening
from tests.helpers import canned_assertion, seed_opening


def test_extract_assertions_appends_not_truncates(tmp_path: Path) -> None:
    """extract_and_persist_assertions is append-only: a second call appends, not replaces (Wall 6)."""
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn, "opening", company_id="co")

    fake_ext = FakeExtractor(
        [[canned_assertion("craft_direction")], [canned_assertion("trajectory")]]
    )

    extract_and_persist_assertions(
        conn, "opening", "chunk", extractor=fake_ext, rubric_text="rubric"
    )
    extract_and_persist_assertions(
        conn, "opening", "chunk", extractor=fake_ext, rubric_text="rubric"
    )

    assertions = assertions_for_opening(conn, "opening")
    assert len(assertions) == 2, (
        f"Expected 2 persisted assertions, got {len(assertions)}. "
        "append_assertions must never truncate existing rows."
    )
    assert assertions[0].target == "craft_direction"
    assert assertions[1].target == "trajectory"


def test_extract_assertions_each_result_is_valid_assertion(tmp_path: Path) -> None:
    """Every persisted row must parse as a valid Assertion."""
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn, "opening", company_id="co")
    fake_ext = FakeExtractor([[canned_assertion("mission"), canned_assertion("domain")]])
    extract_and_persist_assertions(
        conn, "opening", "chunk", extractor=fake_ext, rubric_text="rubric"
    )

    assertions = assertions_for_opening(conn, "opening")
    assert len(assertions) == 2
    for a in assertions:
        assert a.provenance == "model_proposed"
        assert len(a.citations) >= 1


def test_extract_assertions_skips_db_write_when_extractor_returns_nothing(
    tmp_path: Path,
) -> None:
    """An empty extraction result must not call append_assertions (no-op branch)."""
    conn = connect(tmp_path / "screen.db")
    seed_opening(conn, "opening", company_id="co")
    fake_ext = FakeExtractor([[]])

    result = extract_and_persist_assertions(
        conn, "opening", "chunk", extractor=fake_ext, rubric_text="rubric"
    )

    assert result == []
    assert assertions_for_opening(conn, "opening") == []
