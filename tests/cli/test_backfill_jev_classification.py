"""Unit tests for the `backfill-jev-classification` CLI command — re-classifies every
stored assertion with Jev, dropping confidently-irrelevant ones and refreshing
fit/confidence on the rest. Scoped exception to Wall 6 (decisions.md E6): updates rows
in place rather than appending.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from screen.intake import cli as cli_module
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    assertions_for_opening,
    get_dimension_digest,
    upsert_assertion_ruling,
    upsert_company,
    upsert_dimension_digest,
    upsert_opening,
)
from screen.types import AssertionRuling, Company, Opening
from screen.verdict.classification_protocol import AssertionClassification, AssertionClassifier
from screen.verdict.fakes import FakeAssertionClassifier
from tests.helpers import canned_assertion, env_for


def _seed_opening(db_path: Path, opening_id: str, company_id: str, *, chunk: str = "x") -> str:
    """Seeds one opening with one pre-migration assertion (confidence=None). Returns the
    assertion id."""
    conn = connect(db_path)
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title="Eng",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            created_at=datetime.now(UTC),
        ),
    )
    assertion = canned_assertion("craft_direction")
    assertion = assertion.model_copy(update={"chunk": chunk})
    append_assertions(conn, [assertion], opening_id=opening_id)
    conn.close()
    return assertion.id


def _seed_opening_with_assertion(
    db_path: Path, opening_id: str, company_id: str, assertion: object
) -> None:
    """Like `_seed_opening`, but takes a fully-built assertion — for scenarios where the
    stored row must already carry a specific fit/confidence."""
    conn = connect(db_path)
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title="Eng",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            created_at=datetime.now(UTC),
        ),
    )
    append_assertions(conn, [assertion], opening_id=opening_id)  # type: ignore[list-item]
    conn.close()


def _seed_opening_with_multiple_assertions(
    db_path: Path, opening_id: str, company_id: str, targets: list[str]
) -> list[str]:
    """Seeds one opening with several pre-migration assertions (confidence=None), one per
    target. Returns the assertion ids in the same order."""
    conn = connect(db_path)
    upsert_company(
        conn, Company(id=company_id, name=f"{company_id} Inc", created_at=datetime.now(UTC))
    )
    upsert_opening(
        conn,
        Opening(
            id=opening_id,
            company_id=company_id,
            title="Eng",
            url=f"https://example.com/{opening_id}",
            research_trace_id=f"tx-{opening_id}",
            created_at=datetime.now(UTC),
        ),
    )
    assertions = [
        canned_assertion(target).model_copy(update={"chunk": f"chunk-{i}"})
        for i, target in enumerate(targets)
    ]
    append_assertions(conn, assertions, opening_id=opening_id)
    conn.close()
    return [a.id for a in assertions]


def test_backfill_updates_fit_and_confidence_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Poor", confidence=0.72, is_relevant=True, relevance_confidence=0.9
                )
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    [assertion] = assertions_for_opening(conn, "acme--eng")
    assert assertion.fit == "Poor"
    assert assertion.confidence == pytest.approx(0.72)


def test_backfill_reclassifies_every_assertion_in_an_opening_not_just_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: `any()` over a side-effecting generator short-circuits on the
    first `True`, which previously meant only the first assertion in each opening ever
    got reclassified. An opening with several assertions that all need reclassifying
    must have all of them updated, not just assertion #1."""
    _seed_opening_with_multiple_assertions(
        tmp_path / "screen.db",
        "acme--eng",
        "acme",
        ["craft_direction", "trajectory", "mission"],
    )
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Poor", confidence=0.60, is_relevant=True, relevance_confidence=0.9
                ),
                AssertionClassification(
                    fit="Mixed", confidence=0.70, is_relevant=True, relevance_confidence=0.9
                ),
                AssertionClassification(
                    fit="Strong", confidence=0.80, is_relevant=True, relevance_confidence=0.9
                ),
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    assertions = assertions_for_opening(conn, "acme--eng")
    assert len(assertions) == 3
    assert all(
        a.confidence is not None for a in assertions
    ), "every assertion in the opening must be reclassified, not just the first"
    by_target = {a.target: a for a in assertions}
    assert by_target["craft_direction"].confidence == pytest.approx(0.60)
    assert by_target["trajectory"].confidence == pytest.approx(0.70)
    assert by_target["mission"].confidence == pytest.approx(0.80)


def test_backfill_drops_confidently_irrelevant_assertion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Mixed", confidence=0.5, is_relevant=False, relevance_confidence=0.9
                )
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    assert assertions_for_opening(conn, "acme--eng") == []


def test_backfill_never_drops_an_assertion_the_operator_has_ruled_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A confidently-irrelevant verdict from Jev must not delete an assertion that
    carries an operator ruling — the ruling can't be re-pointed at nothing."""
    assertion_id = _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    conn = connect(tmp_path / "screen.db")
    upsert_assertion_ruling(
        conn,
        AssertionRuling(assertion_id=assertion_id, fit="Strong", created_at=datetime.now(UTC)),
    )
    conn.close()
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Mixed", confidence=0.5, is_relevant=False, relevance_confidence=0.9
                )
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    [assertion] = assertions_for_opening(conn, "acme--eng")
    assert assertion.id == assertion_id


def test_backfill_dry_run_reports_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Poor", confidence=0.72, is_relevant=True, relevance_confidence=0.9
                )
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification,
        ["--dry-run"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "[dry-run]" in result.output
    conn = connect(tmp_path / "screen.db")
    [assertion] = assertions_for_opening(conn, "acme--eng")
    assert assertion.fit == "Strong"  # unchanged: canned_assertion's original fit
    assert assertion.confidence is None


def test_backfill_invalidates_cached_digest_for_touched_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale cached digest's staleness check assumes assertion_count only grows (Wall 6);
    a backfill drop can shrink it, so the digest must be invalidated, not left to look
    falsely fresh."""
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    conn = connect(tmp_path / "screen.db")
    upsert_dimension_digest(
        conn,
        opening_id="acme--eng",
        target="craft_direction",
        digest="stale digest text",
        assertion_count=5,
        computed_at=datetime.now(UTC),
    )
    conn.close()
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Mixed", confidence=0.5, is_relevant=False, relevance_confidence=0.9
                )
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    conn = connect(tmp_path / "screen.db")
    assert get_dimension_digest(conn, "acme--eng", "craft_direction") is None


def test_backfill_reports_opening_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    _seed_opening(tmp_path / "screen.db", "widgets--eng", "widgets")
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Poor", confidence=0.72, is_relevant=True, relevance_confidence=0.9
                )
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert "2/2 opening" in result.output


def test_backfill_dry_run_does_not_delete_a_confidently_irrelevant_assertion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--dry-run` reports a would-be drop but leaves the row in place."""
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Mixed", confidence=0.5, is_relevant=False, relevance_confidence=0.9
                )
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification,
        ["--dry-run"],
        env=env_for(tmp_path),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "[dry-run] drop" in result.output
    conn = connect(tmp_path / "screen.db")
    assert len(assertions_for_opening(conn, "acme--eng")) == 1


def test_backfill_leaves_an_already_current_assertion_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An assertion Jev now returns the same fit/confidence for (e.g. a re-run of an
    already-backfilled opening) is neither dropped nor rewritten, and its opening doesn't
    count toward `openings_touched` — the command is idempotent."""
    already_current = canned_assertion("craft_direction").model_copy(
        update={"fit": "Mixed", "confidence": 0.65}
    )
    _seed_opening_with_assertion(tmp_path / "screen.db", "settled--eng", "settled", already_current)
    _seed_opening(tmp_path / "screen.db", "acme--eng", "acme")
    monkeypatch.setattr(
        cli_module,
        "_build_assertion_classifier",
        lambda: FakeAssertionClassifier(
            [
                AssertionClassification(
                    fit="Mixed", confidence=0.65, is_relevant=True, relevance_confidence=0.9
                ),
                AssertionClassification(
                    fit="Poor", confidence=0.72, is_relevant=True, relevance_confidence=0.9
                ),
            ]
        ),
    )

    result = CliRunner().invoke(
        cli_module.backfill_jev_classification, [], env=env_for(tmp_path), catch_exceptions=False
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "1/2 opening" in result.output
    conn = connect(tmp_path / "screen.db")
    [settled] = assertions_for_opening(conn, "settled--eng")
    assert settled.fit == "Mixed"
    assert settled.confidence == pytest.approx(0.65)


def test_build_assertion_classifier_returns_protocol_instance() -> None:
    """The production factory is safe to call and satisfies `AssertionClassifier`, even
    though the test suite above replaces it with a fake (mirrors
    `test_default_factories_return_protocol_instances` in test_research_batch.py)."""
    assert isinstance(cli_module._build_assertion_classifier(), AssertionClassifier)
