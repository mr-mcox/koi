---
feature: pairwise-ranking
type: bearing
date: 2026-09-17
commit: 6239178
branch: main
status: completed
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

`rank_pool` already accepts a per-dimension covariance and takes the correlated sampling
path when one is supplied (compare-scouting G4) — nothing produces one yet. This node adds
the storage and batch fit that turn operator comparisons into that covariance; the
operator-facing screen ships separately (Not Doing). Terrain:
[scouting.md](./scouting.md), [compare-scouting.md](./compare-scouting.md).

## Done When

- [x] A comparison outcome (A/B/tie on one dimension) is stored append-only and changes
      the pool's rank order when passed into `pool_for_screening` → integration test
      through `pool_for_screening`
- [x] The batch Laplace fit returns a mean vector and covariance matrix per dimension using
      only numpy/`math.erf` → unit test against the toy two-opening numbers in scouting F6
- [x] Two openings at the same company auto-tie on a company-level dimension without a
      stored operator comparison → unit test
- [x] Every comparison event is logged with the model's pre-comparison `P(A beats B)`,
      independent of the fit-selection policy in the next bullet → `tests/test_store.py`
- [x] The pair/dimension picker never offers a dimension where either opening has zero
      assertions, except `domain` → unit test

## Approach

- New append-only `comparisons` table (migration `0010`): pair, dimension, outcome
  (`a`/`b`/`tie`), digest version ids in effect (→ compare-scouting G1, G2, scouting F50, F51→F75, F76)
- `dimension_digests` becomes append-only; "current" is the latest by `assertion_count`
  (→ compare-scouting G2, G3, scouting F49)
- A pure fit function (priors from `TargetStats`, Thurstone probit likelihood, Newton to
  the MAP, Hessian inverse as covariance) returns exactly what `rank_pool`'s existing
  `covariance` parameter accepts; `rank_pool` itself is unchanged. Fit reads the latest
  judgment per (unordered pair, dimension); the calibration log records every event
  regardless (→ compare-scouting G4, G6, scouting F5, F25, F33, F75)
- Same-company auto-tie on company-level dimensions is a generated likelihood term, never a
  stored comparison or calibration-log entry (→ scouting F35→F70)
- Pair/dimension picker (backend only): LUCB-style top-K boundary pairing, dimension by
  variance share, routed to research when either opening lacks evidence — `domain` exempt
  (→ scouting F29, F30, F31, F72)

## Not Doing

- Expected-information-gain pair selection — only if the LUCB picker asks poor questions
  (→ scouting F29)
- Digest-similarity prior — deferred (→ scouting F52, F53)
- Comparing constraints pairwise — they stay absolute multipliers (→ scouting F37)
- Research draw reweighting toward the boundary — research-targeting.md
- The comparison screen, its route, and end-to-end web tests — a later bearing; verified
  here only through `pool_for_screening` integration and unit tests

## Testing

Test-first by default. Exempt: nothing named yet.

## Recalibrate When

- If the LUCB picker repeatedly offers pairs the operator finds obviously settled, stop (→ scouting F29).
- If same-company auto-tie visibly misreads a real divergence, stop (→ scouting F70).
- If the first ~20 comparisons' logged predictions look miscalibrated, stop (→ scouting F81).
- If the Laplace fit can't fit discipline's complexity/length ceilings without scipy, stop
  and escalate the dependency add (→ compare-scouting G5, scouting F86).

## Agreed

- Bayesian Thurstone probit with a batch Laplace fit, not Elo — order-independent, carries
  uncertainty (→ scouting F5, F24)
- Comparisons append-only with full history; fit reads latest per (pair, dimension) (→ scouting F51→F75)
- Digests become append-only; each comparison links the exact versions shown, replacing the in-place upsert (→ scouting F49, F76)
- Every dimension is comparable, including compensation and domain; domain alone is exempt
  from the evidence-required routing rule (→ scouting F36→F71, F72)
