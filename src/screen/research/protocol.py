"""Navigator — the seam the dispatcher uses to call Navigate. Surveyor — the
seam the dispatcher uses to call Survey, once per pass, before any Navigator
turn (decisions.md E9: both read state and propose; the dispatcher owns
every tool call and all state mutation).

runtime_checkable so isinstance() works in tests without inheriting.
"""

from typing import Protocol, runtime_checkable

from screen.research.actions import Action
from screen.research.question import ResearchQuestion
from screen.research.state import LoopState


@runtime_checkable
class Navigator(Protocol):
    def plan(self, state: LoopState) -> list[Action]: ...


@runtime_checkable
class Surveyor(Protocol):
    def survey(self, state: LoopState) -> ResearchQuestion: ...
