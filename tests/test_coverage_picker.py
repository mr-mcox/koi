from datetime import UTC, datetime
from uuid import uuid4

from screen.compare.picker import _settled_pairs, select_comparison
from screen.score.pairwise import Comparison as ScoreComparison
from screen.score.types import ScoringConfig
from screen.types import Assertion, Citation


def _assertion(target: str) -> Assertion:
    return Assertion(
        id=str(uuid4()),
        target=target,  # type: ignore[arg-type]
        fit="Strong",  # type: ignore[arg-type]
        provenance="model_proposed",
        chunk="x",
        citations=[
            Citation(url="http", quote="x", host="h", source_provenance="p", independent=True)
        ],
        created_at=datetime.now(UTC),
    )


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


def test_pair_priority_floor_keeps_pair_selectable():
    # Even when `p_top_k` is 0.0, the floor keeps the pair alive for selection.
    config = ScoringConfig(
        dimension_weights={"mission": 1.0},
        dimension_guards={"mission": False},
        guard_downside=3.0,
        guard_upside=0.3,
        boundary_weight_floor=0.1,
        comparison_beta={"operator": 0.5, "provisional": 1.0},
        seed=1,
        samples=1000,
        provenance_weight={"model_proposed": 1.0, "unexamined": 0.0},
        top_k=5,
        research_block_turns=3,
        jev_confidence_threshold=0.85,
        jev_few_shot_examples=12,
        comparison_jitter_sigma=0.3,
        tie_commit_threshold=0.95,
        winner_commit_threshold=0.85,
    )
    res = select_comparison(
        ["a", "b"],
        companies_by_opening={"a": "c1", "b": "c2"},
        assertions_by_opening={"a": [_assertion("mission")], "b": [_assertion("mission")]},
        comparisons_by_target={},
        p_top_k_by_opening={"a": 0.0, "b": 0.0},
        config=config,
    )
    assert res is not None
    assert res.target == "mission"


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
