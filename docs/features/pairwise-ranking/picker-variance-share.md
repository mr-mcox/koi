---
feature: pairwise-ranking
type: bearing
date: 2026-09-21
commit: 5c5f040
branch: main
status: completed
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

Since `location` became a scored dimension (`constraints-and-rubric.md`, S13), the
comparison picker hands the operator almost nothing but location pairings. The current
picker picks the most ambiguous pair *within each dimension*, then selects the dimension
with the highest weighted ambiguity. `location` has the highest rubric weight (6) and
broad assertion coverage, so it wins the cross-dimension round almost every time. Other
dimensions — `stretch`, `schematic`, `mission`, etc. — have comparable assertion coverage
but lower weights, so they rarely get compared even though the overall rank is still
uncertain along those dimensions. The symptom matches the deferred F30 framing in
`picker-information-gain.md`: dimension choice should be by variance share, not by
weight-corrected per-dimension ambiguity. Terrain: [scouting.md](./scouting.md), F29–F31,
F52–F53, F55.

## Done When

- [x] `select_comparison` chooses a pair and dimension by how much that dimension
      contributes to uncertainty between two openings whose overall rank is close — not by
      the most ambiguous pair within the highest-weight dimension → new unit test
- [x] After `location` comparisons have shrunk a pair's location posterior variance, the
      picker prefers another dimension for that same pair → new unit test
- [x] Same-company auto-ties, evidence-required qualification, and calibration-log
      prediction remain unchanged → existing `tests/test_compare_picker.py` passes
- [x] The change is confined to the picker; `fit_pairwise`, the comparison store, and the
      comparison screen are untouched → code review / grep
- [x] A pair neither side of which could plausibly enter or leave top-K scores near zero
      regardless of closeness, except when the whole pool fits within `top_k` → new unit
      tests
- [x] Dimension choice uses `sqrt(weight)`, not `weight²`, so a high-weight dimension with
      little residual variance doesn't structurally dominate → new unit test
- [x] A seeded jitter term keeps a single low-scoring judgment from permanently sinking a
      pair's priority, and is deterministic given a caller-supplied `rng` → new unit tests
- [x] `comparison_jitter_sigma` is a named `scoring.yaml` dial, loaded through
      `ScoringConfig`/`loader.py`, not a constant hidden in code → code review

## Approach

- Replace the current two-level loop (best pair per dimension → best dimension) with a
  single pool-wide score over every candidate `(pair, dimension)`:

  1. Compute each dimension's posterior mean vector and covariance for its qualified
     openings, reusing `_dimension_posterior` / `fit_pairwise`.
  2. For each pair, compute the overall score-difference mean and variance as the
     weighted sum across dimensions (dimensions are independent across the score rollup).
  3. Derive `P(A beats B)` overall and its closeness to 0.5.
  4. For each `(pair, dimension)`, score it as
     `closeness_overall × weight_d² × var_diff_d`. The weight-squared term makes the
     score proportional to that dimension's contribution to total score variance; the
     closeness term keeps focus on rank contests that are actually unsettled.
  5. Return the `(pair, dimension)` with the highest score.

- `var_diff_d` is the posterior variance, so a dimension whose comparisons have already
  shrunk it — `location` ties on a stuck pair, for example — naturally scores lower. The
  explicit per-pair shrinkage ratio can be retired inside the selection formula because the
  posterior already encodes the shrinkage.

- Same-company pairs on company-level dimensions stay excluded; auto-tie likelihood terms
  still feed `fit_pairwise` so the posterior reflects them.

- The evidence-required qualification rule (`_qualify_for_dimension`) is unchanged.

## Not Doing

- Full LUCB top-K boundary pair selection (F29) — this bearing changes *dimension* choice
  for the picked pair, not the pair-selection strategy itself.
- Digest-similarity / cross-opening prior (F52) — still deferred; W5 says precedent shows,
  it never decides, and this change does not move scores automatically.
- Rubric weight changes — if variance-share alone still under-asks low-weight dimensions,
  that becomes a separate weight-tuning decision, not bundled here.
- Research-vs-compare routing — `research-targeting.md` owns that.

## Testing

- Test-first by default. New tests:
  - `test_variance_share_rebalances_after_location_shrinks`: after location comparisons
    collapse a pair's location variance, the picker switches to another dimension.
  - `test_variance_share_prefers_uncertain_rank_contest`: given two pairs, one already
    decisively separated overall and one close, the close contest wins even if the
    decisive one has a higher-weight ambiguous dimension.
- Existing `tests/test_compare_picker.py` must pass; update any test whose previous
  assertion encoded the old weight-first behavior only if the new behavior is clearly
  superior for that fixture.

## Recalibrate When

- If the picker starts flitting between dimensions and never asks enough questions on
  any one dimension to shrink its variance, stop — the closeness term may be too dominant.
- If `domain` (weight 1) still never gets asked because heavier dimensions' residual
  variance dominates, stop and consider a weight adjustment as a separate change.
- If the first live batch of comparisons still feels like "location only" to the operator,
  stop and look at whether location assertions themselves are too noisy (F55), not the
  picker.

## Agreed

- Dimension choice by variance share within the overall rank-uncertain pair, replacing
  max weighted per-dimension ambiguity (→ operator, F30).
- Posterior variance already carries the "how much is left to learn" signal; no separate
  per-pair shrinkage ratio is needed inside the new score (→ operator).

## Amendment (2026-09-21): weight² dimension scoring recreated the lock; boundary and jitter added

Live-data simulation (greedy pick + tie feedback, 33-opening pool) showed the shipped
`closeness × weight_d² × var_diff_d` formula reproduces the original bug: all dimensions
start at similar prior variance (0.13–0.31), so `location`'s weight²=36 outscores
`domain`'s weight²=1 on nearly every pair regardless of how little location evidence is
left to gather — 100-round simulation gave `location` 36%, five dimensions 0%. A second,
independent gap surfaced in the same simulation: `closeness_overall` measures how contested
a pair is *against each other*, not against the `top_k` boundary — pairs both ranked ~22
scored identically to pairs near rank 5, so the picker could spend rounds distinguishing
two openings neither of which can reach top-K (operator: "if I end up spending a bunch of
time scoring stretch on an opportunity at rank 25 because location has already ruled it
out, that goes against use operator time efficiently").

**Revised score**, still fully deterministic apart from the named jitter term:

```
closeness_overall × boundary_weight(max(p_top_k_a, p_top_k_b)) × sqrt(weight_d) × var_diff_d × jitter
```

- `boundary_weight(p) = p · (1-p)` — reused verbatim from `score/bandit.py`, built for the
  identical purpose on the research-draw side (research-targeting.md). `max` over the pair
  (not `mean`): a pair still matters if *either* side could still move into or out of
  top-K. Verified against live data: a rank-3-vs-rank-30 pair scores ~0.0002, three orders
  of magnitude below the top real candidate (~0.06) — the tail-noise failure mode is closed.
- `sqrt(weight_d)`, not `weight_d²`, for dimension choice within an already-contested pair.
  `weight²` is kept in `closeness_overall` (correct there — it's measuring the real rubric
  rollup) but dropped to `sqrt` for choosing *which* dimension to ask about, because pair
  selection and dimension selection are different questions: "is this pair's rank in doubt"
  legitimately scales with the rubric, but "what do I know least about here" is dominated by
  weight under any exponent ≥ 1, on live data, at every jitter level tried. `sqrt` still lets
  weight break ties among similarly-uncertain dimensions without letting it override
  evidence entirely. Simulated over 60 rounds: 10-11 of 11 dimensions get asked, vs. 3 of 11
  under weight¹ and 1 of 11 under weight².
- Jitter: `score *= exp(N(0, σ))`, log-normal so the (always non-negative) score can't go
  negative, threaded through a seeded `np.random.Generator` the same way `bandit.draw_opening`
  already threads one — reproducible per `config.seed`, not reseeded per call. Purpose: a
  single tie/loss that sinks a pair's score shouldn't make it structurally unreachable
  forever (operator: "a call that I made that sent something lower doesn't keep it at the
  bottom forever"). `σ = 0.3` chosen empirically — the smallest value at which every
  dimension gets sampled at least once over 60 simulated rounds (0.15 still leaves one
  dimension untouched); worst-case best-side rank among picks stays close to the
  zero-jitter baseline through σ=0.5, degrading only above σ=0.8–1.2. New `scoring.yaml`
  dial `comparison_jitter_sigma`, same unmeasured-placeholder status as `top_k`.

**Not Doing (unchanged), plus:**
- LUCB-style boundary *pair* selection beyond `boundary_weight` (full F29) — the simpler
  multiplicative term closes the observed tail-noise gap; a dedicated LUCB pass is only
  worth it if this still asks about clearly-settled pairs on live data.
- Digest-similarity / cross-opening kernel prior (F52) — raised again by the operator this
  session, third time in recent weeks; still deferred here, but see `open-questions.md` OQ17
  for the standing note this session added.

**Recalibrate When (adds to the above):**
- If live comparisons still cluster on 1-2 dimensions despite jitter, raise `σ` before
  reworking the formula again.
- If jitter visibly surfaces a pair the operator finds absurd (e.g. two openings that are
  both clearly out), lower `σ` — the boundary term should already suppress this; a
  regression here means the boundary term itself needs revisiting, not just the jitter
  scale.

**Agreed (adds to the above):**
- Dimension choice uses `sqrt(weight)`, not `weight²` — pair selection and dimension
  selection are different questions and only the former should scale with the full rubric
  weight (→ operator, live-data simulation this session).
- `boundary_weight(max(p_top_k))` gates every candidate pair so operator time is never spent
  distinguishing two openings that can't reach top-K (→ operator).
- Small log-normal jitter (σ=0.3, empirically chosen) keeps a low-scoring pair reachable
  rather than permanently sunk by one judgment (→ operator).