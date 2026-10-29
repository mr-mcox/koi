from screen.compare.picker import ComparisonSuggestion, select_comparison
from screen.score.pairwise import Comparison as ScoreComparison
from screen.score.types import ComparisonBetaParams, ScoringConfig
from tests.helpers import canned_assertion


def _mission_config() -> ScoringConfig:
    return ScoringConfig(
        dimension_weights={"mission": 1.0},
        dimension_guards={"mission": False},
        guard_downside=3.0,
        guard_upside=0.3,
        boundary_weight_floor=0.1,
        comparison_beta=ComparisonBetaParams(operator=0.5, provisional=1.0),
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


def test_pair_priority_floor_keeps_pair_selectable():
    # Even when `p_top_k` is 0.0, the floor keeps the pair alive for selection.
    config = _mission_config()
    res = select_comparison(
        ["a", "b"],
        companies_by_opening={"a": "c1", "b": "c2"},
        assertions_by_opening={
            "a": [canned_assertion("mission")],
            "b": [canned_assertion("mission")],
        },
        comparisons_by_target={},
        p_top_k_by_opening={"a": 0.0, "b": 0.0},
        config=config,
    )
    assert res is not None
    assert res.target == "mission"


def _pick_after_operator_ruling(
    current_digest_ids: dict[tuple[str, str], str],
) -> ComparisonSuggestion | None:
    ruling = ScoreComparison(
        winner="a",
        loser="b",
        provenance="operator",
        winner_digest_version="digest-a1",
        loser_digest_version="digest-b1",
    )
    return select_comparison(
        ["a", "b"],
        companies_by_opening={"a": "c1", "b": "c2"},
        assertions_by_opening={
            "a": [canned_assertion("mission")],
            "b": [canned_assertion("mission")],
        },
        comparisons_by_target={"mission": [ruling]},
        p_top_k_by_opening={"a": 0.5, "b": 0.5},
        config=_mission_config(),
        current_digest_ids=current_digest_ids,
    )


def test_operator_ruling_on_current_digests_is_settled():
    assert (
        _pick_after_operator_ruling({("a", "mission"): "digest-a1", ("b", "mission"): "digest-b1"})
        is None
    )


def test_operator_ruling_is_askable_again_after_new_evidence_on_one_side():
    suggestion = _pick_after_operator_ruling(
        {("a", "mission"): "digest-a1", ("b", "mission"): "digest-b2"}
    )
    assert suggestion is not None
    assert suggestion.target == "mission"


def test_operator_ruling_is_askable_when_a_side_has_no_current_digest():
    assert _pick_after_operator_ruling({("a", "mission"): "digest-a1"}) is not None
