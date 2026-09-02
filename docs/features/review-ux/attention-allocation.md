---
feature: review-ux
type: bearing
date: 2026-09-01
commit: b071c22
branch: main
status: decomposed
scouting: ./attention-allocation-scouting.md
---

## Problem

The queue optimizes cattle, not pets — 10+ intake'd openings, and the operator wants to
apply to the top K (~10, growing) each week for the least time spent. The queue needs one
signal that tells the operator, and the two attention bandits (research, rating), whether
an opening's position relative to the top-K cutoff is still worth spending time on, or
already settled. Terrain: [attention-allocation-scouting.md](./attention-allocation-scouting.md).

## Done When

- [ ] The queue exposes a `P(rank crosses K)` value per opening, computed once and
      reusable by both the computation and any future display work (→ scouting F29, F33)

## Approach

- Boundary = the `standing` of whichever opening currently holds rank K in the queue;
  crossing-probability for every other opening = fraction of samples where its `overall`
  trace exceeds the K-th opening's `overall` trace, both drawn under the shared
  `config.seed` (→ scouting F33)
- One queue, one new signal — no second sorted view, no guided-triage screen, no
  reach-sort lens; `standing` stays the only sort key (→ scouting F27, F28, decisions S4/S5)
- The crossing-probability value is display/route-layer only, computed by comparing two
  already-produced traces — never written back to `Assertion`/`DimensionRuling`/`Scorer`
  (→ scouting F16, F33)
- Research-bandit and rating-bandit candidate lists both read the same crossing-probability
  signal to pick which openings are still contested; they differ only in which action
  they offer against a contested opening, not in a separate leverage computation (→
  scouting F25, F31)
- The computation and its display are separately reviewable and iterate at different
  rates — split rather than one bearing (this session)

## Not Doing

- Modeling the operator's review session (intake → research → rating → apply-or-repeat)
  as a persisted state machine — it's a sequencing heuristic for humans, not a system
  object (→ scouting F34)
- A half-width/settledness-aware research counterfactual distinguishing "searched, found
  nothing" from "never attempted" — F4's gap is real but only matters as a tiebreak inside
  an already-contested opening (→ scouting F19)
- Approach-EV or any weighting of affordances — an affordance is filed as an ordinary
  assertion and moves the opening through the existing scoring path, no new mechanism (→
  scouting F24, open-questions.md #5)
- A pairwise or resampled multi-opening comparison for the boundary — the fixed K-th-trace
  reference is the deliberately cheap approximation (→ scouting F30, F33)
- Pipeline-stage modeling — treat the backlog as one uniform stage (→ scouting F32)

## Testing

Test-first by default. Exempt: nothing named at this level — each child names its own.

## Recalibrate When

- Real queue data shows rank K's identity churning turn-to-turn such that the fixed
  K-th-trace reference materially misrepresents crossing probability — stop (→ scouting
  F33)
- A real session shows the operator wanting to rate an opening before its research pass
  completes — stop, batching research before rating (F34) needs to become interleaving
  instead (→ scouting F34)

## Agreed

- Reject the earlier three-lens plan (guided-triage / sort-by-standing / sort-by-reach) —
  raw `reach` was already barred from sorting because it saturates, and a third guided
  view would duplicate the new signal (→ scouting F28)
- Best-effort over precision at the boundary: the K-th-trace comparison is chosen for its
  low implementation/latency cost (→ scouting F30, F33)
- Research runs before rating within a review session, not interleaved per-opening — the
  operator decides when to stop and apply to the top L (→ scouting F34)
- Split into two leaves: computation (stable, testable) and display (expected to iterate,
  supersedes `sort-and-presentation-scouting.md`'s open display threads) — the reversal
  cost of getting the glyph wrong is low and shouldn't gate the metric (this session)
