"""Navigator — the seam the dispatcher uses to call Navigate. Surveyor — the
seam the dispatcher uses to call Survey, once per pass, before any Navigator
turn (decisions.md E9: both read state and propose; the dispatcher owns
every tool call and all state mutation). LinkScorer — the seam the dispatcher
uses to rank the outbound-link backlog before the first navigator turn.

runtime_checkable so isinstance() works in tests without inheriting.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from screen.research.actions import Action
from screen.research.question import ResearchQuestion
from screen.research.state import LoopState


@runtime_checkable
class Navigator(Protocol):
    def plan(self, state: LoopState) -> list[Action]: ...


@dataclass(frozen=True)
class LinkScore:
    """One scored backlog candidate. `p_relevant` is a calibrated probability that
    the link carries more evidence for the active research question."""

    url: str
    p_relevant: float


@runtime_checkable
class LinkScorer(Protocol):
    """Scores outbound links against the active target/question/rubric."""

    def score_links(
        self,
        rubric_text: str,
        primary_target: str,
        research_question: str,
        links: list[tuple[str, str]],
    ) -> list[LinkScore]: ...


@runtime_checkable
class Surveyor(Protocol):
    def survey(self, state: LoopState) -> ResearchQuestion: ...
