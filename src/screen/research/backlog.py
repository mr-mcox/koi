"""Backlog ranking: turn the unvisited outbound links replayed from prior passes
into a short, ordered shortlist for the navigator's prompt.

Separate from the navigator because it is a different judgment made by a
different model: the navigator picks the next action, the `LinkScorer` estimates
per-link relevance. The dispatcher composes them.
"""

from collections.abc import Callable

from screen.research.protocol import LinkScorer
from screen.research.state import LoopState

# Candidates sent to the scorer, and shortlist handed to the navigator. The first
# caps per-pass scoring cost; the second caps prompt size (scouting F14-F16: after
# aggregator hosts are filtered, the candidate cap is rarely reached).
_MAX_CANDIDATES = 100
_MAX_SHORTLIST = 20


def rank_link_backlog(
    state: LoopState,
    link_scorer: LinkScorer,
    link_allowed: Callable[[str], bool] | None = None,
) -> list[str]:
    """Score `state.unvisited_links` against the active dimension, best first.

    `link_allowed`, when given, drops candidates whose host the wiring layer
    refuses (intake's declined hosts, plus aggregator chrome).
    """
    if not state.unvisited_links or state.primary_target is None:
        return []

    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for text, url in state.unvisited_links:
        if url in seen:
            continue
        seen.add(url)
        if link_allowed is not None and not link_allowed(url):
            continue
        candidates.append((text, url))
    candidates = candidates[:_MAX_CANDIDATES]

    scores = link_scorer.score_links(
        rubric_text=state.rubric_text,
        primary_target=state.primary_target,
        research_question=state.research_question or "",
        links=candidates,
    )
    score_by_url = {s.url: s.p_relevant for s in scores}
    ranked = sorted(candidates, key=lambda c: score_by_url.get(c[1], 0.0), reverse=True)
    return [url for _, url in ranked[:_MAX_SHORTLIST]]
