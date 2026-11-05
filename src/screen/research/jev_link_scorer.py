"""Live `LinkScorer` adapter: Jev (TypeSafe's System One model) scores outbound
links for how likely they are to provide more evidence for the active research
question.

Exempt from unit-test coverage (`[tool.coverage.run] omit` in `pyproject.toml`):
calls the paid TypeSafe API. Unit tests inject a fake scorer via the Protocol
instead.
"""

from typesafe_sdk import Noul, NoulAnswer, NoulCriteria, TypeSafeClient

from screen.research.protocol import LinkScore

_LINK_CRITERIA = NoulCriteria(
    true="The link is likely to provide additional evidence for the active research question.",
    false="The link is likely to be navigation, boilerplate, or otherwise unhelpful for the active research question.",
)


class JevLinkScorer:
    """Scores outbound links with Jev and returns calibrated relevance probabilities."""

    def __init__(self, client: TypeSafeClient | None = None) -> None:
        self._explicit_client = client
        self._client: TypeSafeClient | None = None

    def score_links(
        self,
        rubric_text: str,
        primary_target: str,
        research_question: str,
        links: list[tuple[str, str]],
    ) -> list[LinkScore]:
        if not links:
            return []
        if self._client is None:
            self._client = self._explicit_client or TypeSafeClient()

        state = {
            "rubric": rubric_text,
            "primary_target": primary_target,
            "research_question": research_question,
            "links": [{"text": text, "url": url} for text, url in links],
        }
        questions = {
            f"link_{i}": Noul(
                instructions=(
                    f"Does link {i} (text: {text!r}, url: {url}) likely provide more evidence "
                    f"for the research question {research_question!r} on target {primary_target!r}?"
                ),
                criteria=_LINK_CRITERIA,
            )
            for i, (text, url) in enumerate(links)
        }
        response = self._client.system_one(state, questions)

        scored: list[LinkScore] = []
        for i, (_, url) in enumerate(links):
            answer = response.answers[f"link_{i}"]
            if not isinstance(answer, NoulAnswer):
                raise ValueError(f"Jev returned a non-Noul answer for link_{i}: {answer!r}")
            scored.append(LinkScore(url=url, p_relevant=answer.noul))
        return scored
