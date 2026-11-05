"""Unit tests for backlog ranking — the shortlist the dispatcher hands the navigator."""

from typing import Any

from screen.research.backlog import rank_link_backlog
from screen.research.protocol import LinkScore
from screen.research.state import LoopState


class _FakeLinkScorer:
    """Scores links from a url -> p_relevant table; records each call's kwargs."""

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores = scores or {}
        self.calls: list[dict[str, Any]] = []

    def score_links(
        self,
        rubric_text: str,
        primary_target: str,
        research_question: str,
        links: list[tuple[str, str]],
    ) -> list[LinkScore]:
        self.calls.append(
            {
                "rubric_text": rubric_text,
                "primary_target": primary_target,
                "research_question": research_question,
                "links": links,
            }
        )
        return [LinkScore(url=url, p_relevant=self._scores.get(url, 0.0)) for _text, url in links]


def _state(
    *,
    unvisited_links: list[tuple[str, str]],
    primary_target: str | None = "compensation",
    research_question: str | None = "What is total comp?",
) -> LoopState:
    return LoopState(
        opening_id="op-abc",
        company_id="co-xyz",
        company_name="Acme Corp",
        opening_title="Staff Software Engineer",
        page_content="Some posting text.",
        url="https://example.com/jobs/1",
        rubric_text="compensation: ...",
        assertions=[],
        turn_budget=5,
        turns_used=0,
        primary_target=primary_target,
        research_question=research_question,
        unvisited_links=unvisited_links,
    )


def test_rank_link_backlog_returns_empty_without_links() -> None:
    scorer = _FakeLinkScorer()
    assert rank_link_backlog(_state(unvisited_links=[]), scorer) == []
    assert scorer.calls == []


def test_rank_link_backlog_returns_empty_without_primary_target() -> None:
    """The scorer judges relevance *to a dimension*; with none chosen there is
    nothing to score against, so the backlog must not be sent at all."""
    scorer = _FakeLinkScorer()
    state = _state(
        unvisited_links=[("Engineering blog", "https://acme.com/blog")],
        primary_target=None,
        research_question=None,
    )
    assert rank_link_backlog(state, scorer) == []
    assert scorer.calls == []


def test_rank_link_backlog_orders_by_score_descending() -> None:
    scorer = _FakeLinkScorer(
        {
            "https://acme.com/low": 0.10,
            "https://acme.com/high": 0.90,
            "https://acme.com/mid": 0.50,
        }
    )
    state = _state(
        unvisited_links=[
            ("Low", "https://acme.com/low"),
            ("High", "https://acme.com/high"),
            ("Mid", "https://acme.com/mid"),
        ]
    )
    assert rank_link_backlog(state, scorer) == [
        "https://acme.com/high",
        "https://acme.com/mid",
        "https://acme.com/low",
    ]


def test_rank_link_backlog_deduplicates_by_url_keeping_first_text() -> None:
    scorer = _FakeLinkScorer({"https://acme.com/page": 0.5})
    state = _state(
        unvisited_links=[
            ("First text", "https://acme.com/page"),
            ("Second text", "https://acme.com/page"),
        ]
    )
    assert rank_link_backlog(state, scorer) == ["https://acme.com/page"]
    assert scorer.calls[0]["links"] == [("First text", "https://acme.com/page")]


def test_rank_link_backlog_excludes_disallowed_hosts() -> None:
    scorer = _FakeLinkScorer({"https://allowed.com/page": 0.5})
    state = _state(
        unvisited_links=[
            ("Allowed", "https://allowed.com/page"),
            ("Blocked", "https://blocked.com/page"),
        ]
    )
    ranked = rank_link_backlog(state, scorer, lambda u: "blocked.com" not in u)
    assert scorer.calls[0]["links"] == [("Allowed", "https://allowed.com/page")]
    assert ranked == ["https://allowed.com/page"]


def test_rank_link_backlog_caps_candidates_sent_to_the_scorer() -> None:
    """Scoring is paid per link; an unbounded replay must not become an unbounded bill."""
    scorer = _FakeLinkScorer()
    state = _state(unvisited_links=[(f"text{i}", f"https://acme.com/{i}") for i in range(150)])
    rank_link_backlog(state, scorer)
    assert len(scorer.calls[0]["links"]) == 100


def test_rank_link_backlog_truncates_to_top_twenty() -> None:
    scorer = _FakeLinkScorer({f"https://acme.com/{i}": 1.0 - (i * 0.01) for i in range(30)})
    state = _state(unvisited_links=[(f"text{i}", f"https://acme.com/{i}") for i in range(30)])
    ranked = rank_link_backlog(state, scorer)
    assert len(ranked) == 20
    assert ranked[0] == "https://acme.com/0"
