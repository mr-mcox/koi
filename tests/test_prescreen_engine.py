"""Acceptance tests for the comparison pre-screen engine: walks confident provisional
verdicts to completion (or a turn cap), reporting each one to a progress dict so a
polling web route can render them landing live — same shape as `BatchEngine`/`run_batch`,
applied to the comparison gate instead of research turns."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from screen.api.pool import CompareProgress, run_prescreen
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    append_comparison,
    comparisons_for_target,
    upsert_company,
    upsert_dimension_digest,
    upsert_opening,
)
from screen.types import Assertion, Citation, Company, Comparison, Opening
from screen.verdict.protocol import FewShotExample, RubricVerdict

_NOW = datetime(2026, 9, 17, tzinfo=UTC)
_CITATION = Citation(
    url="https://example.com/note",
    quote="verbatim source text",
    host="example.com",
    source_provenance="official",
    independent=True,
    source_date=None,
)


def _assertion(target: str, fit: str) -> Assertion:
    return Assertion(
        target=target,  # type: ignore[arg-type]
        fit=fit,  # type: ignore[arg-type]
        provenance="ratified",
        chunk="verbatim source text",
        citations=[_CITATION],
        created_at=_NOW,
    )


class _FixedVerdict:
    def __init__(self, outcome: str, confidence: float) -> None:
        self._outcome = outcome
        self._confidence = confidence

    def rule(
        self,
        rubric_text: str,
        digest_a: str,
        digest_b: str,
        few_shot_examples: list[FewShotExample],
    ) -> RubricVerdict:
        return RubricVerdict(outcome=self._outcome, confidence=self._confidence)  # type: ignore[arg-type]


def _seed(conn, digest_a: str, digest_b: str) -> None:  # type: ignore[no-untyped-def]
    upsert_company(conn, Company(id="acme", name="Acme", created_at=_NOW))
    upsert_company(conn, Company(id="widgets", name="Widgets", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--a",
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/a",
            research_trace_id="tx" + "0" * 18,
            created_at=_NOW,
        ),
    )
    upsert_opening(
        conn,
        Opening(
            id="widgets--b",
            company_id="widgets",
            title="Staff Engineer",
            url="https://example.com/b",
            research_trace_id="tx" + "1" * 18,
            created_at=_NOW,
        ),
    )
    append_assertions(
        conn,
        [_assertion("location", "Strong"), _assertion("craft_direction", "Strong")],
        opening_id="acme--a",
    )
    append_assertions(
        conn,
        [_assertion("location", "Strong"), _assertion("craft_direction", "Poor")],
        opening_id="widgets--b",
    )
    upsert_dimension_digest(
        conn,
        opening_id="acme--a",
        target="location",
        digest=digest_a,
        assertion_count=1,
        computed_at=_NOW,
    )
    upsert_dimension_digest(
        conn,
        opening_id="widgets--b",
        target="location",
        digest=digest_b,
        assertion_count=1,
        computed_at=_NOW,
    )


def test_run_prescreen_persists_confident_verdicts_and_reports_progress(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "US remote, no twin-cities office")
    config = load_scoring_config()
    progress = CompareProgress()
    run_prescreen(
        conn,
        config,
        verdict_provider=_FixedVerdict("tie", 1.0),
        progress=progress,
    )

    assert progress.running is False
    assert len(progress.ruled) == 1
    assert progress.ruled[0].target == "location"
    assert progress.ruled[0].outcome == "tie"
    assert progress.ruled[0].provenance == "provisional"
    assert {progress.ruled[0].opening_a_id, progress.ruled[0].opening_b_id} == {
        "acme--a",
        "widgets--b",
    }
    assert len(comparisons_for_target(conn, "location")) == 1
    # location is settled; the operator is handed the dimension Jev never ruled on.
    assert progress.final_suggestion is not None
    assert progress.final_suggestion.target == "craft_direction"


def test_run_prescreen_reports_nothing_when_jev_is_never_confident(tmp_path: Path) -> None:
    """Below threshold, the operator still sees what Jev actually read (outcome and
    confidence) on the pair it couldn't settle — so an uncertain verdict is visibly
    different from Jev never having been asked at all."""
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "US remote, no twin-cities office")
    config = load_scoring_config()
    progress = CompareProgress()

    run_prescreen(
        conn,
        config,
        verdict_provider=_FixedVerdict("tie", 0.1),
        progress=progress,
    )

    assert progress.running is False
    assert progress.ruled == []
    assert comparisons_for_target(conn, "location") == []
    assert progress.final_suggestion is not None
    assert progress.final_suggestion.target == "location"
    assert progress.final_suggestion_jev_read == RubricVerdict(outcome="tie", confidence=0.1)


def test_run_prescreen_reports_no_jev_read_without_a_cached_digest(tmp_path: Path) -> None:
    """When there's no cached digest, Jev is never consulted at all — `final_suggestion`
    is set but `final_suggestion_jev_read` stays `None`, distinguishing "never asked"
    from "asked but uncertain"."""
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme", created_at=_NOW))
    upsert_company(conn, Company(id="widgets", name="Widgets", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--a",
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/a",
            research_trace_id="tx" + "0" * 18,
            created_at=_NOW,
        ),
    )
    upsert_opening(
        conn,
        Opening(
            id="widgets--b",
            company_id="widgets",
            title="Staff Engineer",
            url="https://example.com/b",
            research_trace_id="tx" + "1" * 18,
            created_at=_NOW,
        ),
    )
    append_assertions(conn, [_assertion("location", "Strong")], opening_id="acme--a")
    append_assertions(conn, [_assertion("location", "Strong")], opening_id="widgets--b")
    config = load_scoring_config()
    progress = CompareProgress()

    class _ExplodingVerdict:
        def rule(
            self,
            rubric_text: str,
            digest_a: str,
            digest_b: str,
            few_shot_examples: list[FewShotExample],
        ) -> RubricVerdict:
            raise AssertionError("verdict provider should not be called without cached digests")

    run_prescreen(conn, config, verdict_provider=_ExplodingVerdict(), progress=progress)

    assert progress.final_suggestion is not None
    assert progress.final_suggestion.target == "location"
    assert progress.final_suggestion_jev_read is None


def test_run_prescreen_completes_with_no_suggestion_when_pool_cannot_pair(
    tmp_path: Path,
) -> None:
    """A single-opening pool has no pair to suggest — the loop returns on its first
    iteration with nothing ruled and nothing left to show the operator."""
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--a",
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/a",
            research_trace_id="tx" + "0" * 18,
            created_at=_NOW,
        ),
    )
    config = load_scoring_config()
    progress = CompareProgress()

    run_prescreen(conn, config, verdict_provider=_FixedVerdict("tie", 1.0), progress=progress)

    assert progress.completed is True
    assert progress.ruled == []
    assert progress.final_suggestion is None
    assert progress.final_suggestion_jev_read is None


def test_run_prescreen_sources_few_shot_examples_from_operator_rulings(tmp_path: Path) -> None:
    """A prior operator ruling with a cached digest feeds the few-shot sourcing path; a
    prior ruling naming an opening with no cached digest is skipped, not an error."""
    conn = connect(tmp_path / "screen.db")
    upsert_company(conn, Company(id="acme", name="Acme", created_at=_NOW))
    upsert_company(conn, Company(id="widgets", name="Widgets", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="acme--a",
            company_id="acme",
            title="Staff Engineer",
            url="https://example.com/a",
            research_trace_id="tx" + "0" * 18,
            created_at=_NOW,
        ),
    )
    upsert_opening(
        conn,
        Opening(
            id="widgets--b",
            company_id="widgets",
            title="Staff Engineer",
            url="https://example.com/b",
            research_trace_id="tx" + "1" * 18,
            created_at=_NOW,
        ),
    )
    append_assertions(conn, [_assertion("location", "Strong")], opening_id="acme--a")
    append_assertions(conn, [_assertion("location", "Strong")], opening_id="widgets--b")
    upsert_dimension_digest(
        conn,
        opening_id="acme--a",
        target="location",
        digest="US remote, no twin-cities office",
        assertion_count=1,
        computed_at=_NOW,
    )
    upsert_dimension_digest(
        conn,
        opening_id="widgets--b",
        target="location",
        digest="US remote, no twin-cities office",
        assertion_count=1,
        computed_at=_NOW,
    )
    upsert_opening(
        conn,
        Opening(
            id="acme--c",
            company_id="acme",
            title="Other Engineer",
            url="https://example.com/c",
            research_trace_id="tx" + "2" * 18,
            created_at=_NOW,
        ),
    )
    append_assertions(conn, [_assertion("location", "Strong")], opening_id="acme--c")
    append_comparison(
        conn,
        Comparison(
            id="prior-ruling",
            opening_a_id="acme--a",
            opening_b_id="acme--c",
            target="location",
            outcome="tie",
            provenance="operator",
            predicted_a_beats_b=0.5,
            created_at=_NOW,
        ),
    )
    config = load_scoring_config()
    progress = CompareProgress()

    run_prescreen(
        conn,
        config,
        verdict_provider=_FixedVerdict("tie", 1.0),
        progress=progress,
        max_iterations=1,
    )

    assert len(progress.ruled) == 1
    assert len(comparisons_for_target(conn, "location")) == 2
