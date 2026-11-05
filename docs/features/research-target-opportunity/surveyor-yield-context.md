---
feature: research-target-opportunity
type: bearing
date: 2026-11-04
commit: TBD
branch: main
status: orienting
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

The Surveyor (`survey.baml`) currently receives empty yield context: a hardcoded
placeholder string `NOT_YET_AVAILABLE` for `yield_summary`. It knows how many
assertions each dimension has, but not whether that's because the dimension is
productive (high yield rate) or because research exhausted the budget before
striking anything real. This is context a model-driven chooser needs: target a
dimension the operator called "unlikely to bear fruit" and you're wasting turns;
target one that's stalled elsewhere but yields 60% of the time, and you have a
real signal.

Pool-wide baseline (all 387 `decide_plan` events from `data/live`):
- agentic: 60.3% (60/91)
- compensation: 65.2% (60/92)
- craft_direction: 61.5% (16/26)
- domain: 60.3% (47/78)
- mission: 59.3% (16/27)
- internal_culture: 46.3% (25/54) ← notably weak
- location: 25.0% (4/16) ← very weak
- trajectory: 100.0% (1/1) ← no signal (n=1)
- schematic: 50.0% (1/2) ← no signal (n=2)

And per-opening counts matter: if a dimension has never yielded on *this* opening
but yields 60% pool-wide, that's an unexamined hypothesis, not a stall signal.

## Done When

- [x] `render_yield_summary(opening_id, pool_yield, stalls)` → renders per-dimension
  yield rates paired with pool-wide baseline, one-liner per dimension, scoped to
  the current opening's stall counts
- [x] `half_width_per_dimension(opening_yield)` → computes a simple Bayesian
  posterior width (pool prior + this-opening likelihood) or a frequentist confidence
  interval, so the Surveyor knows which dimension's rate is most uncertain
- [x] Both renderers are tested; `question.py` no longer uses `NOT_YET_AVAILABLE`
  placeholder for `yield_summary`
- [x] `dispatcher._survey_request(state)` passes actual `yield_summary` built from
  the opening's events
- [x] Test traces with new `yield_summary` field added to `SurveyRequest`
- [x] `uv run python scripts/check.py` passes

## Approach

- `fold_target_yield(plans)` already exists (replay.py) and yields pool-wide rates;
  it's called at the start of each opportunity to seed `PassState.yield_state`
- Pair pool yield against this-opening stall counts: a dimension with 0/3 runs on
  this opening + 65% pool rate is "not yet tried"; 0/3 runs + 25% pool rate is
  "stalled relative to average"
- Render as: `agentic (66%): 2 yielded of 3 attempts, pool baseline 65.9%`
- `half_width` is secondary; a frequentist 90% CI margin around the pool rate is
  acceptable as a first cut (e.g., ±8% for n=91, ±11% for n=54)
- Call site: `dispatcher.py` lines 116–130 (`_survey_request`), currently hardcoding
  `yield_summary=NOT_YET_AVAILABLE`

## Not Doing

- Blending per-opening counts into a posterior point estimate (that's the Surveyor's
  job, not ours) — we render both the opening's observed rate and the pool baseline
  and let the model decide what to do with the uncertainty
- Stratifying by time, company sector, role level, or job-market cycle — pool-wide
  is the signal for now
- Bayesian credible intervals (too much machinery for an uncertain signal; frequentist
  CI margin is simpler and defensible)

## Testing

Test-first in `tests/research/test_question.py`:
- `render_yield_summary` on a realistic per-opening distribution (some dims 0/n, some
  with varied n, one with full pool)
- `half_width_per_dimension` over the pool data
- Integration: call site in `dispatcher._survey_request` computes it correctly

## Recalibrate When

- If the Surveyor consistently ignores the yield rate (always picks the lowest
  or always the highest) — the framing may not be using the signal
- If pool-wide yield on a dimension shifts more than ±5% after N more openings
  — consider recaching and recomputing
- If `half_width` margins make a decision between dimensions flaky (e.g., all
  dimensions within margin) — a different uncertainty model may be needed

## Agreed

- One line per dimension in the `yield_summary` string, not a separate JSON object
  (keeps it composable with other context renderers)
- Pool-wide is computed once at the start of a pass, not refreshed mid-pass
- Old traces (before this feature) carry an empty string for `yield_summary` rather
  than the placeholder, so replay doesn't need a fallback
