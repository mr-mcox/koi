"""Sources few-shot examples for a verdict provider from the operator's existing
stored rulings — the rubric nuance the rubric text alone doesn't capture is in how the
operator has actually judged real pairs, not a hand-written example set.
"""

from __future__ import annotations

import numpy as np

from screen.types import Comparison
from screen.verdict.protocol import FewShotExample


def few_shot_examples_from_rulings(
    comparisons: list[Comparison],
    digests_by_opening: dict[str, str],
    *,
    rng: np.random.Generator,
    max_examples: int,
) -> list[FewShotExample]:
    """Every operator ruling with a cached digest on both sides is eligible; a ruling
    naming an opening with no digest is skipped — there's no evidence to show the
    provider. Above `max_examples`, a random subset is drawn so the provider sees a
    different sample each calibration pass rather than a fixed, possibly-biased one."""
    eligible = [
        FewShotExample(
            digest_a=digests_by_opening[c.opening_a_id],
            digest_b=digests_by_opening[c.opening_b_id],
            outcome=c.outcome,
        )
        for c in comparisons
        if c.opening_a_id in digests_by_opening and c.opening_b_id in digests_by_opening
    ]
    if len(eligible) <= max_examples:
        return eligible
    indices = rng.choice(len(eligible), size=max_examples, replace=False)
    return [eligible[i] for i in indices]
