"""Acceptance tests for sourcing few-shot examples from the operator's existing stored
rulings: every operator `Comparison` on a target with digests on both sides is eligible;
missing a digest on either side excludes it (nothing to show Jev); above the cap, a
random subset is drawn so the provider doesn't see a fixed, possibly-biased set every
calibration pass."""

from datetime import UTC, datetime

import numpy as np

from screen.types import Comparison
from screen.verdict.few_shot import few_shot_examples_from_rulings
from screen.verdict.protocol import FewShotExample

_NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _comparison(opening_a_id: str, opening_b_id: str, outcome: str) -> Comparison:
    return Comparison(
        opening_a_id=opening_a_id,
        opening_b_id=opening_b_id,
        target="location",
        outcome=outcome,  # type: ignore[arg-type]
        predicted_a_beats_b=0.5,
        created_at=_NOW,
    )


def test_every_ruling_with_both_digests_is_eligible() -> None:
    comparisons = [_comparison("a", "b", "tie"), _comparison("c", "d", "a")]
    digests = {"a": "digest a", "b": "digest b", "c": "digest c", "d": "digest d"}

    examples = few_shot_examples_from_rulings(
        comparisons, digests, rng=np.random.default_rng(0), max_examples=10
    )

    assert set(examples) == {
        FewShotExample(digest_a="digest a", digest_b="digest b", outcome="tie"),
        FewShotExample(digest_a="digest c", digest_b="digest d", outcome="a"),
    }


def test_ruling_missing_a_digest_on_either_side_is_excluded() -> None:
    comparisons = [_comparison("a", "b", "tie"), _comparison("a", "missing", "a")]
    digests = {"a": "digest a", "b": "digest b"}

    examples = few_shot_examples_from_rulings(
        comparisons, digests, rng=np.random.default_rng(0), max_examples=10
    )

    assert examples == [FewShotExample(digest_a="digest a", digest_b="digest b", outcome="tie")]


def test_above_the_cap_a_random_subset_is_drawn() -> None:
    comparisons = [_comparison(f"a{i}", f"b{i}", "tie") for i in range(10)]
    digests = {f"a{i}": f"digest a{i}" for i in range(10)} | {
        f"b{i}": f"digest b{i}" for i in range(10)
    }
    eligible = few_shot_examples_from_rulings(
        comparisons, digests, rng=np.random.default_rng(0), max_examples=10
    )

    sampled = few_shot_examples_from_rulings(
        comparisons, digests, rng=np.random.default_rng(0), max_examples=3
    )

    assert len(sampled) == 3
    assert set(sampled) <= set(eligible)
