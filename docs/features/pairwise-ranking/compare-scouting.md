---
feature: pairwise-ranking
type: scouting
date: 2026-09-17
commit: 6239178
parent: ./bearing.md
---

## What We're Doing

rank-pool.md is done (bearing.md's first Done When item, S9/S10/S11 recorded). This node
scouts the second: **pairwise comparisons by the operator move the ranking.** Parent
scouting.md already carries the operator's framing and agreements (F1-F86); this file adds
only what a fresh read of the current code contributes.

## Findings

- **G1** — `src/screen/store/repo.py:83-90` — `upsert_assertion_ruling` is a real precedent
  for a new upsert-vs-append choice, but comparisons need append (parent F51→F75: keep full
  history), so this is the wrong shape to copy; `append_assertions` (`repo.py:63-71`) is the
  shape to copy instead.
- **G2** — `src/screen/store/migrations/0004_create_dimension_digests.sql` — digests are
  `PRIMARY KEY (opening_id, target)`, upserted in place on regeneration. Parent F49/F76:
  this must become append-only (a `version`/`id` column) so a comparison can reference the
  exact digest text the operator saw. No migration yet touches this.
- **G3** — `src/screen/digest/service.py:39-60` — `digest_for_target` returns the digest
  string only, keyed by staleness (`assertion_count`). A comparison record needs the digest
  *row id* (or version), not just its text, to satisfy G2.
- **G4** — `src/screen/score/scorer.py:94-98,163-164` — `rank_pool` already accepts an
  optional `covariance: dict[str, np.ndarray]` per dimension and takes the correlated path
  when present; this is the seam compare.md fills, not a scorer change. `_sample_dimension_gaussian`
  (diagonal path, `scorer.py:85-92`) is the fallback for dimensions with no comparisons yet.
- **G5** — `pyproject.toml` — no scipy dependency; confirmed no `scipy` importable in the
  venv. Parent F25's constraint holds: the Thurstone Laplace fit (Φ, Newton, Hessian
  inverse) must use `numpy`/`math.erf` only, or add a dependency (which Approach in
  bearing.md already forecloses as an escalation-worthy add per the architecture girder
  "no agent framework" spirit — adding scipy is a dependency-add tripwire either way).
- **G6** — `src/screen/api/scoring.py:26-44` — `pool_for_screening` is the one assembly
  point from stored rows to `PoolInput`/`rank_pool`; a comparison-fitted covariance would
  be assembled here too, alongside rulings, keeping routes free of scoring math.
- **G7** — `src/screen/web/routes.py:55-62,204-233` — `_rating_context` and
  `_dimension_groups` are the existing per-opening read path (digest + assertions grouped
  by target); a compare screen needs the same shape for *two* openings side by side, so
  factoring `_dimension_groups` for two-opening reuse is in scope, not a parallel
  implementation.
- **G8** — `src/screen/score/types.py:52-58` — `PoolInput` already carries a docstring note
  that it "does not carry `dimension_rulings`"; no equivalent doc yet says it carries (or
  doesn't carry) comparison-derived covariance — that lands wherever this bearing places
  the covariance assembly (G6).
- **G9** — `src/screen/store/migrations/` — next migration number is `0010`
  (parent F51 already found this); confirms no comparison migration has landed since.
- **G10** — `tests/test_scorer.py` — the correlated-covariance path (G4) has no test yet
  exercising `covariance=` with real numbers beyond shape; a comparison-fit test suite is
  new territory, not an extension of an existing one.
