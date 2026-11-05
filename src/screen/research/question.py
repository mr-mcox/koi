"""ResearchQuestion — the Surveyor's output: one rubric dimension worth
investigating this pass, framed as a specific question. `dimension` is `str`,
not `Target`: validating it against the live rubric vocabulary is the
dispatcher's job (it decides what happens on a bad answer), not a parse-time
concern of this type.
"""

import math
from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from screen.research_trace.replay import TargetYield
from screen.types import Assertion


class ResearchQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: Annotated[str, Field(min_length=1)]
    question: Annotated[str, Field(min_length=1)]


def half_width_per_dimension(pool_yield: dict[str, TargetYield]) -> dict[str, float]:
    """Compute frequentist 90% confidence interval margin around the pool rate."""
    margins: dict[str, float] = {}
    for target, y in pool_yield.items():
        if y.runs == 0:  # pragma: no cover — fold_target_yield drops empty targets
            margins[target] = 0.0
            continue  # pragma: no cover — fold_target_yield drops empty targets
        p = y.yielded / y.runs
        # 90% CI for proportion is 1.645 * sqrt(p * (1 - p) / n)
        margins[target] = 1.645 * math.sqrt(p * (1 - p) / y.runs)
    return margins


def render_yield_summary(
    opening_id: str, pool_yield: dict[str, TargetYield], stalls: dict[str, int]
) -> str:
    """Render per-dimension yield rates paired with pool-wide baseline."""
    lines: list[str] = []
    # Using sorted keys to make rendering deterministic
    for target in sorted(pool_yield.keys()):
        y = pool_yield[target]
        pool_rate = (y.yielded / y.runs) * 100 if y.runs > 0 else 0.0
        stall_count = stalls.get(target, 0)

        if y.runs == 0:
            lines.append(f"{target}: no pool baseline yet")
            continue

        lines.append(
            f"{target} ({pool_rate:.1f}%): 0 yielded of {stall_count} attempts on {opening_id}, pool baseline {pool_rate:.1f}%"
        )

    return "\n".join(lines)


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
