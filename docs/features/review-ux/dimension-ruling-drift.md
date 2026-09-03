
feature: review-ux
type: bearing
date: 2026-08-31
commit: 3984752
branch: resumable-research
status: implementing
scouting: ./dimension-ruling-drift-scouting.md
---

## Problem

A `DimensionRuling` pin (`review-ux/dimension-ruling.md`, done) is computed against the
assertions that existed at ruling time and never moves again — `n=inf` in the Scorer makes
it un-outweighable by any later evidence (scouting F1/F2). New assertions filed under a
pinned target should erode the pin's weight, drifting the target's stats back toward the
plain assertion aggregate, and the triage surface should re-offer that target for rating
once enough has changed. Terrain: [dimension-ruling-drift-scouting.md](./dimension-ruling-drift-scouting.md).

## Done When

- [ ] `DimensionRuling` stamps the assertion ids covered at ruling time (→ scouting F17)
      → `tests/test_types.py`
- [ ] `stats_for_target` blends a pin as a Bayesian prior into the same shrinkage sum
      `_target_stats` already runs (prior weight `n_pin = 1/half_width^2`, derived from
      `settledness` via the existing `hw_max`/`hw_min` bounds, no new config dial), instead
      of returning `_dimension_ruling_stats`'s `n=inf` override — test: a pin with zero new
      assertions since stamping produces the exact same `mean`/`half_width` as today's hard
      override (no regression on the shipped contract); a pin with new assertions
      accumulating under it moves `standing` measurably toward the unpinned aggregate, and
      enough new weight can move it arbitrarily close (→ scouting F3, F14, F18) →
      `tests/test_scorer.py`
- [ ] A pin's pre-existing (covered) assertions never independently move the blend — only
      assertions whose id is outside the stamped snapshot count as "new" evidence in the
      blend — test: rating (confirming or overriding) a pre-existing assertion underneath
      a pin changes nothing, matching the currently-shipped
      `test_dimension_ruling_override_ignores_assertion_level_rulings_for_same_target`
      unmodified (→ scouting F5, F14) → `tests/test_scorer.py`
- [ ] A `backfill-dimension-ruling-covered-assertion-ids` CLI command (following the
      `backfill-research-turns-budget` blanket-reset precedent) populates
      `covered_assertion_ids` for existing `dimension_rulings` rows from the assertions
      currently filed under each ruling's target — the exact historical snapshot as of
      the ruling's own `created_at` isn't reconstructable once newer assertions have
      landed, so this approximates it as "current assertions at backfill time" and is
      safe to re-run — test: existing rows gain non-empty `covered_assertion_ids` matching
      current assertions for that `(opening_id, target)` (→ scouting F17, F21, operator) →
      `tests/cli/test_backfill_dimension_ruling_covered_assertion_ids.py`
- [ ] `rating_task_candidates` re-offers a pinned target as a candidate once any assertion
      exists under it with an id outside the pin's covered snapshot, ranked by the existing
      best-vs-worst swing computation run against the post-drift blended stats — test: a
      pin diluted by a 2nd assertion (1 covered) ranks above one diluted by a 10th (9
      covered), holding weights equal (→ scouting F11, F19) → `tests/test_triage.py`
- [ ] The rating pad shows a third, visually distinct border state for a stale pin —
      unpinned (`border: 1px solid var(--rule)`), fresh pin (`border: 2px solid var(--ink)`),
      stale pin (new, using `--ink-muted`) — test: route/template test asserts the stale
      class renders only when covered ids don't cover all current target assertions (→
      scouting F20) → route integration test, same exemption class as existing template
      tests
- [ ] Existing dimension-ruling, triage, and scoring tests pass unmodified except the one
      new-assertion-blend path they didn't previously exercise

## Approach

- Add `DimensionRuling.covered_assertion_ids: list[str]` (frozen, like the rest of the
  type), stamped from the target's assertion ids at submit time — exact partitioning, no
  count/weight approximation (→ scouting F17, operator)
- Reframe `stats_for_target`'s pin branch: instead of `_dimension_ruling_stats` returning
  a standalone `TargetStats(n=inf, ...)`, treat the pin as a Bayesian prior over
  `_target_stats`'s existing shrinkage sum — the same role its default `(n=1, mean=0)`
  prior already plays for an ordinary unexamined target. The pin's prior weight is derived
  from its own half_width (`n_pin = 1/half_width^2`), not a new dial: a zero-conviction pin
  (`settledness=0`, `half_width=hw_max=1.0`) carries exactly `n_pin=1`, matching the
  ordinary prior's strength; a maximum-conviction pin (`half_width=hw_min=0.05`) carries
  `n_pin≈400`. Assertions covered by the pin's snapshot are excluded from the sum
  entirely, so only uncovered evidence blends in — reusing the shrinkage formula's shape
  rather than inventing a second one, so S8's "provenance widens, never multiplies" is
  inherited rather than re-earned (→ scouting F3, F4, F14)
- No floor under the pin's asymptotic erosion — `n` growing without bound already drives
  the blend toward the unpinned aggregate's mean; no second dial needed (→ scouting F18,
  operator)
- Triage reopening stays binary (any uncovered assertion re-surfaces the candidate); the
  *ranking* among reopened candidates is the existing swing computation in
  `triage.py:_swing`, run on post-drift stats — no new leverage formula (→ scouting F11,
  F19, operator)
- `--ink-muted` (already defined, unused for borders) is the stale-pin border color; no
  new CSS variable (→ scouting F20, operator)

## Not Doing

- No new stored "is stale" flag or nomination entity — staleness is computed from
  `covered_assertion_ids` vs. current assertions the same way `DimensionDigest` already
  computes staleness from `assertion_count` (→ scouting F8, F9)
- No Inbox entity — it doesn't exist in code yet and this feature doesn't need it; the
  triage candidate list is the routed surface (→ scouting F12)
- No change to `AssertionRuling`, assertion-level rating, or any non-pinned target's
  scoring path
- No UI text/copy for "N new assertions since" beyond the border state — reappearing in
  triage plus the border is the surfacing mechanism (→ scouting F20, operator)

## Testing

Test-first by default. Exempt:
- Any template/CSS change for the stale-pin border — covered by route integration tests,
  same exemption class as `rating.html`'s existing carve-out

## Recalibrate When

- Folding the pin into `_target_stats`'s sum can't preserve the "pre-existing assertions
  never independently move the blend" guarantee cleanly — stop, the partition-by-id
  design (F14) is wrong and needs rework before continuing
- The derived `n_pin = 1/half_width^2` either (a) never meaningfully erodes with realistic
  assertion counts, or (b) erodes so fast a single new assertion swamps a
  maximum-conviction pin — stop and reconsider whether `hw_max`/`hw_min` need retuning or
  the derivation itself needs a different shape, same status as `bar`/`top_k`

## Agreed

- Stamp assertion ids, not a count or weight-sum — exact partitioning over approximation
  (→ scouting F17, operator)
- Drift is asymptotic toward the unpinned aggregate, no floor — dilution should be able to
  fully wash out a thin pin (→ scouting F18, operator)
- Reopening in triage is binary; ranking among reopened candidates is quantified via the
  existing swing computation, not a new formula (→ scouting F19, operator)
- Add an intermediate border state (stale pin) between unpinned and fresh-pinned, using the
  existing `--ink-muted` token (→ scouting F20, operator)
- A pin's prior weight is derived from its existing `half_width` (`n_pin = 1/half_width^2`),
  not a new `scoring.yaml` dial — the pin already fully determines its own strength via
  `settledness`, so a separate weight knob would be redundant, not just simpler (open space,
  resolved during implementation: F13's "third unmeasured dial" concern doesn't apply)
