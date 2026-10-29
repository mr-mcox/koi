"""Live `AssertionClassifier` adapter: Jev (TypeSafe's System One model) classifies
unclassified assertions for fit (Poor/Mixed/Strong) and relevance.

Exempt from unit-test coverage (`[tool.coverage.run] omit` in `pyproject.toml`):
calls the paid TypeSafe API. Unit tests inject a fake `AssertionClassifier` via the
Protocol instead.
"""

from __future__ import annotations

from typesafe_sdk import Choice, ChoiceAnswer, TypeSafeClient

from screen.extract.prompt import RubricText, fit_anchors_for_dimension
from screen.verdict.classification_protocol import AssertionClassification, AssertionFit


def _narrow_fit(choice: str) -> AssertionFit:
    """Jev's `Choice.choice` is typed `str` — validate at this trust boundary."""
    if choice == "Poor":
        return "Poor"
    if choice == "Mixed":
        return "Mixed"
    if choice == "Strong":
        return "Strong"
    raise ValueError(f"Jev returned a fit choice outside {{Poor, Mixed, Strong}}: {choice!r}")


def _narrow_relevance(choice: str) -> bool:
    """Parse relevance as a Choice (yes/no) rather than Boolean."""
    if choice in ("yes", "Yes", "YES", "true", "True", "TRUE"):
        return True
    if choice in ("no", "No", "NO", "false", "False", "FALSE"):
        return False
    raise ValueError(f"Jev returned a relevance choice that is not yes/no: {choice!r}")


class JevAssertionClassifier:
    """Satisfies `AssertionClassifier`.

    Calls `system_one` with two parallel questions: `fit` (Choice among
    Poor/Mixed/Strong) and `is_relevant` (Choice yes/no); both ride along in
    `state` for Jev to calibrate on.
    """

    def __init__(self, rubric: RubricText, client: TypeSafeClient | None = None) -> None:
        self._rubric = rubric
        self._explicit_client = client
        self._client: TypeSafeClient | None = None

    def classify(self, chunk: str, target: str) -> AssertionClassification:
        if self._client is None:
            self._client = self._explicit_client or TypeSafeClient()

        state = {
            "rubric": self._rubric.for_dimension(target),
            "chunk": chunk,
            "target": target,
        }
        response = self._client.system_one(
            state,
            {
                "is_relevant": Choice(
                    instructions=(
                        "Is this chunk directly relevant to the target dimension? "
                        "If it is generic/cultural language (e.g., 'we value transparency') "
                        "or off-topic, answer 'no'. If it provides concrete evidence about "
                        "the dimension, answer 'yes'."
                    ),
                    criteria={
                        "yes": "concrete, dimension-specific evidence",
                        "no": "generic language or off-topic",
                    },
                ),
                "fit": Choice(
                    instructions=(
                        "Use the dimension rubric above to classify this claim as Poor, Mixed, "
                        "or Strong. Rate it even if you judged it irrelevant above; fit is orthogonal "
                        "to relevance and the claim may still be useful as evidence."
                    ),
                    criteria=fit_anchors_for_dimension(target),
                ),
            },
        )

        is_relevant_answer = response.answers["is_relevant"]
        if not isinstance(is_relevant_answer, ChoiceAnswer):
            raise ValueError(
                f"Jev returned a non-Choice answer for is_relevant: {is_relevant_answer!r}"
            )

        fit_answer = response.answers["fit"]
        if not isinstance(fit_answer, ChoiceAnswer):
            raise ValueError(f"Jev returned a non-Choice answer for fit: {fit_answer!r}")

        return AssertionClassification(
            fit=_narrow_fit(fit_answer.choice),
            confidence=fit_answer.confidence,
            is_relevant=_narrow_relevance(is_relevant_answer.choice),
            relevance_confidence=is_relevant_answer.confidence,
        )
