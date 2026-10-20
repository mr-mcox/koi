from datetime import UTC, datetime
from uuid import uuid4

from screen.score.compare import Comparison as ScoreComparison
from screen.score.compare_picker import _settled_pairs, select_comparison
from screen.score.types import ScoringConfig
from screen.types import Assertion, Citation


def test_settled_pairs_allows_when_digest_version_differs():
    # Provide an operator ruling where the version recorded was "0" but now there is "1" assertion
    comp = ScoreComparison(
        winner="a",
        loser="b",
        provenance="operator",
        winner_digest_version="0",
        loser_digest_version="0",
    )

    cit = Citation(url="http", quote="x", host="h", source_provenance="p", independent=True)
    a1 = Assertion(
        id=str(uuid4()),
        target="mission",
        fit="Strong",
        provenance="model_proposed",
        chunk="x",
        citations=[cit],
        created_at=datetime.now(UTC),
    )
    assertions_by_opening = {"a": [a1]}

    settled = _settled_pairs("mission", [comp], assertions_by_opening)
    assert frozenset({"a", "b"}) not in settled


def test_pair_priority_zero_skips_pair():
    # Use a mock p_top_k that returns 0.0 so pair_priority <= 0.0 hits
    config = ScoringConfig(
        dimension_weights={"mission": 1.0},
        comparison_beta={"operator": 0.5, "provisional": 1.0},
        seed=1,
        samples=1000,
        provenance_weight={"model_proposed": 1.0, "unexamined": 0.0},
        top_k=5,
        research_target_action_cap=3,
        jev_confidence_threshold=0.75,
        jev_few_shot_examples=12,
        comparison_jitter_sigma=0.3,
        tie_commit_threshold=0.90,
        winner_commit_threshold=0.75,
    )
    res = select_comparison(
        ["a", "b"],
        companies_by_opening={"a": "c1", "b": "c2"},
        assertions_by_opening={},
        comparisons_by_target={},
        p_top_k_by_opening={"a": 0.0, "b": 0.0},
        config=config,
    )
    assert res is None


def test_settled_pairs_blocks_when_digest_version_matches():
    comp = ScoreComparison(
        winner="a",
        loser="b",
        provenance="operator",
        winner_digest_version="1",
        loser_digest_version="0",
    )

    cit = Citation(url="http", quote="x", host="h", source_provenance="p", independent=True)
    a1 = Assertion(
        id=str(uuid4()),
        target="mission",
        fit="Strong",
        provenance="model_proposed",
        chunk="x",
        citations=[cit],
        created_at=datetime.now(UTC),
    )
    assertions_by_opening = {"a": [a1]}

    settled = _settled_pairs("mission", [comp], assertions_by_opening)
    assert frozenset({"a", "b"}) in settled
