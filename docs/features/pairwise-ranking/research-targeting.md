---
feature: pairwise-ranking
type: bearing
date: 2026-09-20
commit: 2dc4f80
branch: rank-pool
status: implementing
parent: ./bearing.md
scouting: ./research-targeting-scouting.md
---

## Problem

The batch research draw weight (`aggregate_uncertainty`) ranks openings by how unexamined
they are, blind to rank — a turn can land on an opening that cannot reach top K, or be
withheld from one sitting on the boundary where an answer would move the top 5. Terrain:
[research-targeting-scouting.md](./research-targeting-scouting.md).

## Done When

- [ ] The batch draw weight favors openings near the top-K boundary over equally-unexamined
      openings that are clearly in or clearly out → unit test on a synthetic pool (extends
      `tests/test_bandit.py`'s pattern)
- [ ] A wholly unexamined ("fresh") opening still draws turns at a rate comparable to a
      boundary-contested examined opening → unit test asserting F17's numeric shape holds
      generally, not just in the one worked pool
- [ ] The combination rule is product; a test exercises it and fails if gate (or pure
      uncertainty) is silently substituted → `tests/test_bandit.py` or `tests/test_batch.py`
- [ ] `screen.research.batch`'s per-draw weight recomputation stays within the existing batch
      loop's freshness contract (recomputed every draw, scouting F2, F15) → `tests/test_batch.py`
      passes unmodified in shape (one new dependency, no behavior change to draw cadence)
- [ ] A live batch run's per-draw latency is not visibly slower with the pool call added →
      **needs you**: run a real batch and compare

## Approach

- The combination rule is product (`uncertainty × boundary`); the decision is recorded here
  in §Agreed and the calculation is isolated so the rule can be changed without a refactor
  (→ scouting F16, F19, F20, F21)
- The boundary signal is assembled where `opening_weight` already lives
  (`research/batch.py`), calling `rank_screening_pool` once per weight recomputation — same
  cadence `eligible_weights` already runs at, no new caching layer (→ scouting F2, F4, F12, F15)
- `aggregate_uncertainty` stays a pure function in `score/bandit.py`, untouched; the new
  boundary term is a second pure function taking a `PoolScoreResult` (or a plain
  `{opening_id: p_top_k}` mapping), not a modification of it — mirrors the existing split
  between per-target (`baml_planner.rank_targets`) and per-opening ranking (→ scouting F1, F8, F9, F10)
- `screen.research.batch` gains an import on `screen.api.pool`; no new dependency direction
  crosses a named girder (→ scouting F3)

## Not Doing

- Changing `baml_planner.rank_targets` (which target within a chosen opening) — orthogonal,
  operates one level down (→ scouting F10)
- A cached or precomputed pool score shared across draws within one batch — recompute every
  draw, matching today's `eligible_weights` contract (→ scouting F2, F15)

## Testing

Test-first by default. Exempt: nothing named yet.

## Recalibrate When

- If a batch run's per-draw latency becomes visibly slower with the pool call added, stop —
  the operator decides caching vs. lowering `samples` (→ scouting F13, F14; rank-pool.md's
  own precedent for this tradeoff)
- If the boundary weight and the uncertainty weight disagree often enough that a clearly
  under-examined boundary opening still starves, stop and revisit the combination rule
  (→ scouting F19, F20, F21)

## Agreed

- Product (`uncertainty × boundary`), not gate — research is breadth-first, raising
  fresh/under-examined openings over fine-grained settling of already-examined boundary
  cases; the queue's wide rank band already lets the operator discount a high-ranked opening
  that still needs research (→ scouting F16, F21)
