"""Live `VerdictProvider` adapter: Jev (TypeSafe's System One model) rules a candidate
pair `a`/`b`/`tie` against the rubric text, returning its own calibrated confidence.

Exempt from unit-test coverage (see `pyproject.toml` / `scripts/check.py` OMIT lists):
calls the paid TypeSafe API. Unit tests inject a fake `VerdictProvider` via the Protocol
instead, mirroring `baml_digester` / `baml_extractor` / `fastembed_embedder`.
"""

from __future__ import annotations

from typesafe_sdk import Choice, ChoiceAnswer, TypeSafeClient

from screen.verdict.protocol import FewShotExample, RubricVerdict, VerdictOutcome

_CRITERIA = {
    "a": "digest_a scores higher than digest_b on this rubric dimension",
    "b": "digest_b scores higher than digest_a on this rubric dimension",
    "tie": "the rubric would score digest_a and digest_b the same on this dimension",
}


def _narrow_outcome(choice: str) -> VerdictOutcome:
    """Jev's `Choice.choice` is typed `str` — the SDK can't statically guarantee it's
    one of our criteria keys. Validate at this trust boundary rather than trust it."""
    if choice == "a":
        return "a"
    if choice == "b":
        return "b"
    if choice == "tie":
        return "tie"
    raise ValueError(f"Jev returned a choice outside {{a, b, tie}}: {choice!r}")


class JevVerdictProvider:
    """Satisfies `VerdictProvider`. Calls `system_one` with a single `Choice` question
    among {a, b, tie}; few-shot examples ride along in `state` for Jev to calibrate on."""

    def __init__(self, client: TypeSafeClient | None = None) -> None:
        self._client = client or TypeSafeClient()

    def rule(
        self,
        rubric_text: str,
        digest_a: str,
        digest_b: str,
        few_shot_examples: list[FewShotExample],
    ) -> RubricVerdict:
        state = {
            "rubric": rubric_text,
            "digest_a": digest_a,
            "digest_b": digest_b,
            "few_shot_examples": [
                {"digest_a": ex.digest_a, "digest_b": ex.digest_b, "outcome": ex.outcome}
                for ex in few_shot_examples
            ],
        }
        response = self._client.system_one(
            state,
            {
                "verdict": Choice(
                    instructions=(
                        "Rule which digest the rubric would score higher on this "
                        "dimension, or tie if the rubric would score them the same."
                    ),
                    criteria=_CRITERIA,
                )
            },
        )
        answer = response.answers["verdict"]
        if not isinstance(answer, ChoiceAnswer):
            raise ValueError(f"Jev returned a non-Choice answer for a Choice question: {answer!r}")
        return RubricVerdict(outcome=_narrow_outcome(answer.choice), confidence=answer.confidence)
