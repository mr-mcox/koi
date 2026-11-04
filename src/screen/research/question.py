"""ResearchQuestion — the Surveyor's output: one rubric dimension worth
investigating this pass, framed as a specific question. `dimension` is `str`,
not `Target`: validating it against the live rubric vocabulary is the
dispatcher's job (it decides what happens on a bad answer), not a parse-time
concern of this type.
"""

from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from screen.types import Assertion


class ResearchQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: Annotated[str, Field(min_length=1)]
    question: Annotated[str, Field(min_length=1)]


# Placeholder for the one Survey input `render_assertion_history` doesn't cover yet:
# per-dimension yield rates. That renderer is a follow-up
# cycle; this one stays a placeholder until it lands.
NOT_YET_AVAILABLE = "(not yet available — yield-rate rendering lands in a follow-up cycle)"


def render_assertion_history(assertions: Iterable[Assertion], targets: Iterable[str]) -> str:
    """Render each target's own assertions — fit, verbatim chunk, citation URLs —
    grouped by dimension, in the order `targets` lists them.
    An assertion whose target isn't in `targets` is excluded: callers scope the
    view by what they pass. The Navigator passes its one fixed target; the
    Surveyor passes every dimension because it is choosing among them.

    A target with no assertions renders as explicitly unexamined rather than
    being omitted. Omission reads as "nothing to say," which a model cannot
    distinguish from "already checked and clean" — and that ambiguity is what
    sends it searching for evidence it already has.
    """
    by_target: dict[str, list[Assertion]] = {}
    for assertion in assertions:
        by_target.setdefault(assertion.target, []).append(assertion)

    sections: list[str] = []
    for target in targets:
        sections.append(f"### {target}")
        items = by_target.get(target, [])
        if not items:
            sections.append("(unexamined — no assertions yet)")
            continue
        for item in items:
            urls = ", ".join(dict.fromkeys(c.url for c in item.citations))
            sections.append(f"- [{item.fit}] {item.chunk}\n  sources: {urls}")
    return "\n".join(sections)
