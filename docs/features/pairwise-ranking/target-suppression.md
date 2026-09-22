---
feature: pairwise-ranking
type: bearing
date: 2026-09-21
commit: (pending)
branch: rank-pool
status: proposed
parent: ./bearing.md
scouting: ./target-suppression-scouting.md
---

## Problem

A live batch run showed roughly half its draws adding zero new assertions. The planner
gets sticky on a target with no findable answer (no engineering blog, no public
hiring-manager contact), burns its per-pass action cap searching variants of the same
query, then a *later, separate* resume re-ranks from scratch and picks the exact same
dead-end target again — nothing in the ranking signal remembers that a target has
already been tried and failed. Terrain: [target-suppression-scouting.md](./target-suppression-scouting.md).

## Done When

- [ ] A target that stalled (an active-target run that ended without adding any
      assertion for that target) ranks below an equally-unexamined target on the next
      pass → unit test extending `test_baml_planner.py`'s `rank_targets` tests
- [ ] The suppression is graduated (S-curve), not a hard cutoff: one stall causes a
      slight dip, two a sharper one, three-or-more is unlikely-but-not-impossible to be
      picked again → unit test on the pure shaping function's values at s=0,1,2,3,4
      (scouting F8)
- [ ] Stall counts are derived from the research trace on every resume, not a new
      persisted DB field → unit test on the trace-walking fold function using a
      synthetic trace fixture (scouting F5, F10, F11)
- [ ] A live batch run against the two known dead-end openings (Vetcove `a4fbea`,
      Airbnb `98c489`) no longer repeats the same stalled target on a subsequent draw →
      **needs you**: run a real batch and check the console trace

## Approach

- New pure function alongside `boundary_weight` (`score/bandit.py` or a sibling),
  `target_suppression(stall_count: int) -> float`, a logistic decay centered near
  `s=1.5` — family A from scouting F8, giving `suppression(0)≈1`, `(1)≈0.88`,
  `(2)≈0.12`, `(3)≈0.006` (→ scouting F7, F8)
- `rank_targets` (`baml_planner.py`) multiplies each target's uncertainty by
  `target_suppression(stall_count)` before sorting — same structural pattern as
  `research-targeting.md`'s `uncertainty * boundary_weight`, one level down (opening
  choice untouched, target choice within a drawn opening gets the new term) (→ scouting F9)
- `replay_research_trace` (`research_trace_replay.py`) gains a new fold producing
  `target_stalls: dict[str, int]` by segmenting the event stream into contiguous
  same-`active_target` runs (from each `decide_plan` event's `request.active_target`)
  and counting a run as a stall when `targets_covered` never grew to include that
  target by the run's end (→ scouting F5, F6, F11)
- `LoopState` gains a new field (e.g. `target_stall_counts: dict[str, int] = {}`),
  populated from `TraceReplay` at `run_dispatch`'s state construction — no schema
  change, no persisted counter, matching the trace-is-the-only-source-of-truth
  invariant `research_trace_replay.py` already documents (→ scouting F10)
- No reset/decay of a stall count once recorded — a target picking up an assertion via
  a different active-target run's cross-target crediting already drops its base
  uncertainty term on its own; the multiplier needs no separate memory of that (→
  scouting F12)

## Not Doing

- Changing the opening-level draw weight (`eligible_weights`, `score/bandit.py`'s
  `boundary_weight`) — this is `research-targeting.md`'s territory and is unaffected
  (→ scouting F13)
- A hard suppression cutoff (target becomes permanently unselectable) — the S-curve
  floor stays above zero so a target remains theoretically reachable if every other
  target is equally exhausted (→ scouting F8)
- Prompt-level changes to `DecidePlan`'s "avoid repeating a prior query" instruction —
  the fix is in target *selection* upstream of the prompt, not in query phrasing (→
  scouting F4)

## Testing

Test-first by default. Exempt: nothing named yet.

## Recalibrate When

- If a target's stall count still lets the planner pick it again within the same
  session it just stalled on (the per-pass cap should already prevent this, but if the
  new suppression term doesn't compound with it correctly), stop.
- If reconstructing stall counts from the trace proves too expensive per resume (mirrors
  `rank_screening_pool`'s cost concern in `research-targeting.md`'s Recalibrate When),
  stop and consider caching within one batch run.

## Agreed

- (pending operator review of the S-curve family choice in scouting F8)
