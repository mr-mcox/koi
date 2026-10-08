"""Protocol surface for rubric-similarity verdict providers.

Any object satisfying `VerdictProvider` can be injected wherever a pairwise rubric
verdict is needed. The live adapter (Jev, TypeSafe's System One model) and test fakes
both satisfy it. Mirrors `screen.digest.protocol`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

VerdictOutcome = Literal["a", "b", "tie"]


@dataclass(frozen=True)
class FewShotExample:
    """One labeled example shown to a verdict provider to calibrate it to rubric nuance
    the rubric text alone doesn't capture — an operator ruling's digest pair and its
    outcome."""

    digest_a: str
    digest_b: str
    outcome: VerdictOutcome


@dataclass(frozen=True)
class RubricVerdict:
    """A verdict provider's ruling on one pair: the outcome and its own calibrated
    confidence (0-1) — a margin from uncertainty, not a probability."""

    outcome: VerdictOutcome
    confidence: float


@runtime_checkable
class VerdictProvider(Protocol):
    def rule(
        self,
        rubric_text: str,
        digest_a: str,
        digest_b: str,
        few_shot_examples: list[FewShotExample],
    ) -> RubricVerdict: ...
