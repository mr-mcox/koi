"""`band` (S5 · The queue reads a standing/reach pair; reach never sorts —
docs/architecture/decisions.md): what the queue displays for a company, derived from a
`standing`/`reach` pair — not stored on either `ScoreResult` (see domain-model.md's Scorer
section: standing and reach are the same result type scored against two assertion sets,
and band is a function of the pair).
"""

from __future__ import annotations

from screen.score.types import Bands, ScoreResult

Band = str  # one of: "no path", "contender", "established", "capped", "wide open"


def band_for(standing: ScoreResult, reach: ScoreResult, bands: Bands) -> Band:
    """Named for what it implies, not for how good the opening is. Order matters: an opening
    can be both a contender and wide open, and the implied action is to act, not research
    further."""
    if standing.unreachable:
        return "no path"  # over the cliff (S4 · Unreachability is analytic, not sampled)
    if standing.standing >= bands.contender:
        return "contender"
    if reach.standing - standing.standing < bands.settled:
        return "established"  # nothing material left to learn
    if reach.standing < bands.reach_capped:
        return "no path"  # not rescuable by one good pass
    if reach.standing < bands.reach_wide:
        return "capped"  # a known fact limits the upside
    return "wide open"
