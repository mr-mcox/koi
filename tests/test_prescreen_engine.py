"""Acceptance tests for the comparison pre-screen engine: walks confident provisional
verdicts to completion (or a turn cap), reporting each one to a progress dict so a
polling web route can render them landing live — same shape as `BatchEngine`/`run_batch`,
applied to the comparison gate instead of research turns."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from screen.compare.picker import ComparisonSuggestion
from screen.compare.prescreen import (
    CompareCache,
    CompareProgress,
    CompareState,
    run_prescreen,
    run_speculative_prescreen,
)
from screen.score.loader import load_scoring_config
from screen.store.db import connect
from screen.store.repo import (
    append_assertions,
    append_comparison,
    comparisons_for_target,
    insert_dimension_digest,
    upsert_company,
    upsert_opening,
)
from screen.types import Assertion, Citation, Company, Comparison, Opening
from screen.verdict.protocol import FewShotExample, RubricVerdict
from tests.helpers import synthetic_rubric

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
        [
            _assertion("location", "Strong"),
            _assertion("craft_direction", "Strong"),
            _assertion("craft_direction", "Strong"),
        ],
        opening_id="acme--a",
    )
    append_assertions(
        conn,
        [
            _assertion("location", "Poor"),
            _assertion("craft_direction", "Strong"),
            _assertion("craft_direction", "Strong"),
        ],
        opening_id="widgets--b",
    )
    insert_dimension_digest(
        conn,
        opening_id="acme--a",
        target="location",
        digest=digest_a,
        assertion_count=1,
        computed_at=_NOW,
    )
    insert_dimension_digest(
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
        rubric=synthetic_rubric(),
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
        rubric=synthetic_rubric(),
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

    run_prescreen(
        conn,
        config,
        verdict_provider=_ExplodingVerdict(),
        rubric=synthetic_rubric(),
        progress=progress,
    )

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

    run_prescreen(
        conn,
        config,
        verdict_provider=_FixedVerdict("tie", 1.0),
        rubric=synthetic_rubric(),
        progress=progress,
    )

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
    insert_dimension_digest(
        conn,
        opening_id="acme--a",
        target="location",
        digest="US remote, no twin-cities office",
        assertion_count=1,
        computed_at=_NOW,
    )
    insert_dimension_digest(
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
        rubric=synthetic_rubric(),
        progress=progress,
        max_iterations=1,
    )

    assert len(progress.ruled) == 1
    assert len(comparisons_for_target(conn, "location")) == 2


def test_run_prescreen_drops_a_ruling_when_the_operator_wrote_during_the_jev_call(
    tmp_path: Path,
) -> None:
    """Jev's confident verdict is computed against a pool snapshot. If the operator
    records their own comparison while that call is in flight, the verdict describes a
    state that no longer exists — it must be dropped rather than committed, or a stale
    auto-ruling silently lands on top of the operator's fresh judgment."""
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "US remote, no twin-cities office")
    config = load_scoring_config()
    progress = CompareProgress()
    compare_state = CompareState()

    class _VerdictThatRacesTheOperator:
        def rule(
            self,
            rubric_text: str,
            digest_a: str,
            digest_b: str,
            few_shot_examples: list[FewShotExample],
        ) -> RubricVerdict:
            compare_state.version += 1
            return RubricVerdict(outcome="tie", confidence=1.0)

    run_prescreen(
        conn,
        config,
        verdict_provider=_VerdictThatRacesTheOperator(),
        rubric=synthetic_rubric(),
        compare_state=compare_state,
        progress=progress,
        max_iterations=1,
    )

    assert progress.ruled == []
    assert comparisons_for_target(conn, "location") == []


def test_speculative_prescreen_answers_what_follows_the_on_screen_pair(
    tmp_path: Path,
) -> None:
    """The point of speculating during the operator's thinking time is to produce the
    *next* comparison, not the one already on screen. A speculation that returned the
    on-screen triple would be worthless: it would be rejected as `just-written-pair` the
    moment the operator ruled on it, and the wait it was meant to hide would return."""
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "Hybrid, three days in Berlin")
    config = load_scoring_config()
    compare_state = CompareState()
    on_screen = ComparisonSuggestion(
        target="location", opening_a_id="acme--a", opening_b_id="widgets--b"
    )
    compare_cache = CompareCache(version=0, suggestion=on_screen)

    run_speculative_prescreen(
        conn,
        config,
        verdict_provider=_FixedVerdict("tie", 0.0),
        rubric=synthetic_rubric(),
        compare_state=compare_state,
        compare_cache=compare_cache,
    )

    assert compare_cache.speculative is not None
    speculated = compare_cache.speculative
    assert (
        frozenset({speculated.opening_a_id, speculated.opening_b_id}),
        speculated.target,
    ) != (frozenset({"acme--a", "widgets--b"}), "location")
    assert compare_cache.speculative_for == (frozenset({"acme--a", "widgets--b"}), "location")


def test_speculative_prescreen_auto_commits_confident_comparisons(tmp_path: Path) -> None:
    """Speculation is allowed to auto-rule easy follow-on pairs while the operator is
    still deciding the on-screen one, so a maximally confident read should still land in
    the DB instead of being left as a banner the operator has to act on themselves."""
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "US remote, no twin-cities office")
    config = load_scoring_config()
    on_screen = ComparisonSuggestion(
        target="craft_direction", opening_a_id="acme--a", opening_b_id="widgets--b"
    )
    compare_state = CompareState()
    compare_cache = CompareCache(version=0, suggestion=on_screen)

    run_speculative_prescreen(
        conn,
        config,
        verdict_provider=_FixedVerdict("tie", 1.0),
        rubric=synthetic_rubric(),
        compare_state=compare_state,
        compare_cache=compare_cache,
    )

    assert len(comparisons_for_target(conn, "location")) == 1
    assert comparisons_for_target(conn, "craft_direction") == []
    assert compare_state.version == 1
    # The auto-ruling must not disturb the pair the operator is actively reading.
    assert compare_cache.suggestion == on_screen


def test_speculative_prescreen_discards_its_result_if_the_operator_wrote_meanwhile(
    tmp_path: Path,
) -> None:
    """A speculation that lands after the operator has already moved on describes a pool
    that no longer exists. Caching it would hand them a suggestion derived from a state
    two writes back, defeating the stale-by-one bound the cache relies on."""
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "Hybrid, three days in Berlin")
    # The speculated pair must have cached digests on both sides, or Jev is never
    # consulted and the mid-call race this test exercises cannot occur.
    for opening_id in ("acme--a", "widgets--b"):
        insert_dimension_digest(
            conn,
            opening_id=opening_id,
            target="craft_direction",
            digest="Platform work, heavy on integration",
            assertion_count=1,
            computed_at=_NOW,
        )
    config = load_scoring_config()
    compare_state = CompareState()
    compare_cache = CompareCache(
        version=0,
        suggestion=ComparisonSuggestion(
            target="location", opening_a_id="acme--a", opening_b_id="widgets--b"
        ),
    )

    class _OperatorRulesDuringTheCall:
        def rule(
            self,
            rubric_text: str,
            digest_a: str,
            digest_b: str,
            few_shot_examples: list[FewShotExample],
        ) -> RubricVerdict:
            compare_state.version += 1
            return RubricVerdict(outcome="tie", confidence=0.0)

    run_speculative_prescreen(
        conn,
        config,
        verdict_provider=_OperatorRulesDuringTheCall(),
        rubric=synthetic_rubric(),
        compare_state=compare_state,
        compare_cache=compare_cache,
    )

    assert compare_cache.speculative is None


def test_speculative_prescreen_is_a_no_op_with_nothing_on_screen(tmp_path: Path) -> None:
    """There is no "next" to speculate about before the operator has a comparison on
    screen at all — calling it with an empty cache must not touch the DB or Jev."""
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "US remote, no twin-cities office")
    config = load_scoring_config()

    class _ExplodingVerdict:
        def rule(
            self,
            rubric_text: str,
            digest_a: str,
            digest_b: str,
            few_shot_examples: list[FewShotExample],
        ) -> RubricVerdict:
            raise AssertionError("Jev should not be consulted with nothing on screen")

    run_speculative_prescreen(
        conn,
        config,
        verdict_provider=_ExplodingVerdict(),
        rubric=synthetic_rubric(),
        compare_state=CompareState(),
        compare_cache=CompareCache(),
    )

    assert comparisons_for_target(conn, "location") == []


def _seed_third_opening(conn, digest: str) -> None:  # type: ignore[no-untyped-def]
    """A third opening gives the location dimension three comparable pairs, so a
    speculative walk has more than one auto-ruling available to it."""
    upsert_company(conn, Company(id="globex", name="Globex", created_at=_NOW))
    upsert_opening(
        conn,
        Opening(
            id="globex--c",
            company_id="globex",
            title="Staff Engineer",
            url="https://example.com/c",
            research_trace_id="tx" + "2" * 18,
            created_at=_NOW,
        ),
    )
    append_assertions(
        conn,
        [
            _assertion("location", "Mixed"),
            _assertion("craft_direction", "Strong"),
            _assertion("craft_direction", "Strong"),
        ],
        opening_id="globex--c",
    )
    insert_dimension_digest(
        conn,
        opening_id="globex--c",
        target="location",
        digest=digest,
        assertion_count=1,
        computed_at=_NOW,
    )


def test_speculative_prescreen_stops_at_its_iteration_bound(tmp_path: Path) -> None:
    """The bound is what keeps a background speculation from walking the entire
    remaining pool while the operator reads one comparison. With three comparable
    openings a maximally confident Jev has two pairs left to auto-rule; a bound of one
    must leave the second unruled."""
    conn = connect(tmp_path / "screen.db")
    _seed(conn, "US remote, no twin-cities office", "US remote, no twin-cities office")
    _seed_third_opening(conn, "US remote, no twin-cities office")
    config = load_scoring_config()
    on_screen = ComparisonSuggestion(
        target="craft_direction", opening_a_id="acme--a", opening_b_id="widgets--b"
    )

    unbounded_state = CompareState()
    run_speculative_prescreen(
        conn,
        config,
        verdict_provider=_FixedVerdict("tie", 1.0),
        rubric=synthetic_rubric(),
        compare_state=unbounded_state,
        compare_cache=CompareCache(version=0, suggestion=on_screen),
    )
    assert len(comparisons_for_target(conn, "location")) > 1

    conn.close()
    bounded_conn = connect(tmp_path / "bounded.db")
    _seed(bounded_conn, "US remote, no twin-cities office", "US remote, no twin-cities office")
    _seed_third_opening(bounded_conn, "US remote, no twin-cities office")
    bounded_state = CompareState()
    run_speculative_prescreen(
        bounded_conn,
        config,
        verdict_provider=_FixedVerdict("tie", 1.0),
        rubric=synthetic_rubric(),
        compare_state=bounded_state,
        compare_cache=CompareCache(version=0, suggestion=on_screen),
        max_iterations=1,
    )

    assert len(comparisons_for_target(bounded_conn, "location")) == 1
    assert bounded_state.version == 1
    bounded_conn.close()
