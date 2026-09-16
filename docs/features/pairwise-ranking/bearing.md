---
feature: pairwise-ranking
type: bearing
date: 2026-09-16
commit: 3a676c42c8f847be76358b4c7be74106e72cac75
branch: main
status: decomposed
scouting: ./scouting.md
---

## Problem

The operator judges staff-level openings by degree, relative to each other, but the
dimension pad asks for absolute positions plus a stated certainty. They end up clicking
an ordering into it (F4, F65). The queue sorts on `P(> bar)` while the north star is
"which 5 are my front runners" (F1, F2). Constraints scored through `Fit` misread real
location cases (F55). Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] Queue orders the pool by rank, with rank bands and a top-K settledness readout
      → rank-pool.md §Done When
- [ ] Pairwise comparisons by the operator move the ranking → compare.md §Done When
- [ ] Research turns concentrate on openings near the top-K boundary
      → research-targeting.md §Done When
- [ ] Constraints score from situation labels, and `distributed` is a weighted dimension
      → constraints-and-rubric.md §Done When
- [ ] `docs/architecture/decisions.md` supersedes S1, S4, S5 and R3, each carrying its
      rejected alternatives; domain-model §Scorer, §Ruling and walls 7 are rewritten
      → grep `decisions.md` for new entries naming S1, S4, S5, R3

## Approach

- Rank is the only sort key; `bar` stops being a sort key or filter anywhere (→ scouting F2, F10)
- Assertions set a permanent Gaussian prior per opening per dimension; comparisons are
  the likelihood; the Scorer is scoped to the pool, not to one opening (→ scouting F3, F5, F12, F13)
- Anything retiring is removed outright: no shims, no dual paths, no conversion of old
  data into the new model (→ scouting F80, F41)
- Every child builds on rank-pool's pool-scoped Scorer, never on today's per-opening
  `score()` (open space)

## Not Doing

- Digest-similarity prior — deferred, and in tension with W5 (→ scouting F52, F53)
- Splitting `internal_culture` like location — wait for location to prove the pattern (→ scouting F64)
- Expected-information-gain pair selection — only if the simple picker asks poor questions (→ scouting F29)
- Company-name redaction on the comparison screen — halo risk accepted (→ scouting F9)

## Testing

Test-first by default. Exempt: nothing at this level; children name their own.

## Recalibrate When

- If any child needs `bar` back as a sort key or filter, stop (→ scouting F27).
- If any child needs to keep a retired path alive for compatibility, stop (→ scouting F80).
- If a wall in domain-model beyond the ⚠ findings has to bend, stop.

## Agreed

- Sort on `P(rank ≤ K)`, not `P(> bar)` — the north star is the top 5 and reshuffling by
  new openings is expected (→ scouting F1, F2)
- Bayesian Thurstone with a batch Laplace fit, not Elo — order-independent and carries
  uncertainty (→ scouting F5, F24)
- Assertions as a permanent prior, not a temporary scaffold — fresh openings need a
  starting position and constraints multiply on a fixed scale (→ scouting F3, F13)
- Rip off the bandaid — pad, existing dimension rulings, contested review, focus view,
  reach and cliff all retire; no side-by-side `P(> bar)` validation (→ scouting F80, F41, F7, F74, F68, F83, F81)
- The calibration log (the model's prediction recorded before each answer) is the
  validation instrument (→ scouting F33, F81)
