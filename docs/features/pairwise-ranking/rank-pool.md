---
feature: pairwise-ranking
type: bearing
date: 2026-09-16
commit: 3a676c42c8f847be76358b4c7be74106e72cac75
branch: main
status: orienting
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

`score()` scores one opening in isolation against `bar` (F11, F14). Ranking needs a joint
rank distribution across the screening pool, drawn from Gaussian dimension priors whose
covariance compare.md will later fill in. Everything the new model makes obsolete retires
here too. Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] Queue page and `/queue` API order openings by `P(rank ≤ top_k)`, with expected rank
      breaking ties → new ordering tests over a synthetic pool in `tests/test_web.py`, `tests/test_api.py`
- [ ] Each queue row shows a q10–q90 rank band and no decimal probability
      → `tests/test_web.py` asserts band text and the absence of decimals
- [ ] The queue shows top-K settledness: K/K for a fully separated pool, fewer when two
      indistinguishable openings straddle rank K → unit test on the readout
- [ ] Ranks are reproducible under `seed` and independent of opening or assertion order
      → `tests/test_scorer.py`
- [ ] Given a correlated per-dimension covariance, sampled correlation between two openings
      matches it; with no comparisons the covariance is diagonal → unit test
- [ ] A kill-level constraint puts an otherwise-best opening at `P(top K)` ≈ 0 → unit test
- [ ] `/contested`, `/openings/{id}/contested`, `/openings/{id}/focus` and the dimension-ruling
      POST return 404; the rating page shows digests and assertion overrides with no pad
      → `tests/test_web.py`
- [ ] Nothing under `src/` reads `DimensionRuling`, settledness, reach, `unreachable`, the
      cliff ceiling, `crossing_probability`, `bar`, `rating_task_budget` or the
      `dimension_ruling` dials → grep over `src/` and `scoring.yaml` returns nothing
- [ ] The research planner ranks targets without settledness → `tests/test_baml_planner.py`
- [ ] Live queue order and rank bands look plausible → **needs you**: open `/` on live data

## Approach

- One pure pool-scoped entry point takes every screening opening's assertions, assertion
  rulings and config, and returns an openings × samples trace plus the rank readouts.
  The per-opening `score()` and `score_opening` are replaced, not kept alongside
  (→ scouting F12, F26, F80)
- Dimensions are Gaussians variance-matched to today's `TargetStats`, sampled jointly per
  dimension from a mean vector and covariance matrix. That matrix is the seam compare.md
  plugs into; this node ships it diagonal (→ scouting F5, F6, F23)
- Constraints keep today's Fit→tolerability uniform multiplier until
  constraints-and-rubric.md replaces it (→ scouting F11, F13)
- Rank band, `P(top K)` and settledness are computed from the trace on read, never stored
  (→ scouting F21, F26)
- `dimension_rulings` rows stay in the database, unread; no migration drops them (open space)

## Not Doing

- Comparisons, the comparison screen, digest history — compare.md
- Boundary-weighted research draws — research-targeting.md; draws keep assertion half-widths here (→ scouting F73)
- Situation labels, the location split, the compensation rewrite — constraints-and-rubric.md

## Testing

Test-first by default. Exempt:
- `src/screen/web/static/app.css` — styling for the rank band, no behavior

## Recalibrate When

- If rendering `/` on the live pool takes over ~2s, stop: lowering `samples` versus caching is the operator's call.
- If telling rows apart needs decimals, stop (→ domain-model walls 4, scouting F22).
- If the settledness readout disagrees with the operator's gut on live data, stop tuning it (→ scouting F21).
- If the discipline gates force I/O into the pool scorer to fit size limits, stop (→ scouting F86).

## Agreed

- Drop the cliff, not a quantile-based replacement — `P(top K)` ≈ 0 already sinks
  unreachable openings (→ scouting F69, F83)
- Gaussian for every dimension, not Uniform for uncompared ones — one distribution family (→ scouting F23, F83)
- Retire reach, not redefine it on ranks — the rank band covers "room left" (→ scouting F16, F68)
- Retire contested review and the focus view, not keep an assertion-only focus (→ scouting F7, F47, F74)
- Drop existing dimension rulings, not convert them into priors or comparisons (→ scouting F41)
