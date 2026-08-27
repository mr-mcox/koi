"""PlannerProtocol — the seam the dispatcher uses to call DecidePlan.

runtime_checkable so isinstance() works in tests without inheriting.
"""

from typing import Protocol, runtime_checkable

from screen.loop.actions import Action
from screen.loop.state import LoopState


@runtime_checkable
class PlannerProtocol(Protocol):
    def plan(self, state: LoopState) -> list[Action]: ...
