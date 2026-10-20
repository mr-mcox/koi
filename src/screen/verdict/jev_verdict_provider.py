"""Live `VerdictProvider` adapter: Jev (TypeSafe's System One model) answers two
Noul questions about a candidate pair against the rubric text, returning raw answers
that are then routed by pure logic to a verdict.

Exempt from unit-test coverage (see `pyproject.toml` / `scripts/check.py` OMIT lists):
calls the paid TypeSafe API. Unit tests inject a fake provider via the Protocol
instead, mirroring `baml_digester` / `baml_extractor`.
"""

from __future__ import annotations

from typesafe_sdk import Noul, NoulAnswer, NoulCriteria, TypeSafeClient

from screen.verdict.protocol import FewShotExample, JevRuling, NoulJudgment, RubricVerdict
from screen.verdict.routing import route_verdict

_CLEAR_WINNER_CRITERIA = NoulCriteria(
    true="One digest is clearly and materially better than the other on this rubric dimension.",
    false="Neither digest is clearly better; differences are immaterial, tradeoffs balance out, or there is insufficient evidence to distinguish them.",
)

_WINNER_CRITERIA = NoulCriteria(
    true="digest_a scores higher than digest_b on this rubric dimension",
    false="digest_b scores higher than digest_a on this rubric dimension, or the digests are tied",
)


def _judgment(answer: NoulAnswer) -> NoulJudgment:
    return NoulJudgment(p_true=answer.noul)


class JevVerdictProvider:
    """Calls Jev's `system_one` with two parallel Noul questions about a rubric dimension.

    Lazily constructs the client on first use, mirroring the other live adapters — importing
    this module (e.g. at app startup) must not require an API key to be present.

    Returns a `RubricVerdict` routed by `route_verdict` logic: auto-commits high-confidence
    pairs and surfaces uncertain ones to the operator."""

    def __init__(self, client: TypeSafeClient | None = None) -> None:
        self._explicit_client = client
        self._client: TypeSafeClient | None = None

    def rule(
        self,
        rubric_text: str,
        digest_a: str,
        digest_b: str,
        few_shot_examples: list[FewShotExample],
    ) -> RubricVerdict:
        ruling = self.get_ruling(rubric_text, digest_a, digest_b, few_shot_examples)
        decision = route_verdict(ruling)
        return decision.verdict

    def get_ruling(
        self,
        rubric_text: str,
        digest_a: str,
        digest_b: str,
        few_shot_examples: list[FewShotExample],
    ) -> JevRuling:
        """Call Jev and return raw answers without routing logic."""
        if self._client is None:
            self._client = self._explicit_client or TypeSafeClient()

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
                "clear_winner": Noul(
                    instructions="Is there a clear, material winner between digest_a and digest_b according to the rubric?",
                    criteria=_CLEAR_WINNER_CRITERIA,
                ),
                "a_is_better": Noul(
                    instructions="Is digest_a the winner according to the rubric?",
                    criteria=_WINNER_CRITERIA,
                ),
            },
        )

        clear_winner = response.answers["clear_winner"]
        a_is_better = response.answers["a_is_better"]

        if not isinstance(clear_winner, NoulAnswer):
            raise ValueError(f"Jev returned a non-Noul answer for clear_winner: {clear_winner!r}")
        if not isinstance(a_is_better, NoulAnswer):
            raise ValueError(f"Jev returned a non-Noul answer for a_is_better: {a_is_better!r}")

        return JevRuling(
            clear_winner=_judgment(clear_winner),
            a_is_better=_judgment(a_is_better),
        )
