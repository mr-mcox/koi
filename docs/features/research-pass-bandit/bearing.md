---
feature: research-pass-bandit
type: bearing
date: 2026-09-04
commit: 3e76d7d
branch: resumable-research
status: done
scouting: ./scouting.md
---

## Problem

`research-batch N` spends turns round-robin across every opening with budget headroom, with
no notion of which opening's next turn is worth more. The operator wants the batch to
sample openings weighted by remaining uncertainty — spreading turns toward thinner evidence
rather than draining one opening's budget or spreading flatly — plus a visible trace of what
was sampled and how the ranking moved, to build confidence the reallocation is doing
something. Terrain: [scouting.md](./scouting.md).

## Done When

- [ ] A pure function `(per-opening assertions/rulings, ScoringConfig) -> float` returns one
      opening's aggregate uncertainty (dimension-weighted sum of `TargetStats.half_width`,
      constraints weighted at `max(dimension_weights.values())`) — test: an opening with
      only wide-half-width, high-weight targets outranks one with narrow/low-weight targets
      (→ scouting F17, F20, F21)
- [ ] `research-batch N` draws one opening per turn, weighted by that aggregate (openings
      with zero remaining `research_turns_budget` excluded from the draw), spends exactly
      one turn on it, recomputes every remaining candidate's weight from its now-current
      assertions, and redraws — test: over many seeded runs, an opening seeded with
      systematically wider half-widths receives turns more often than a narrow one, and a
      fully-budget-exhausted opening never gets drawn (→ scouting F16, F22)
- [ ] Each turn prints one line to stdout: the opening drawn, its draw-time
      weight/probability among eligible candidates, and its aggregate-half-width rank
      before vs. after the turn's new assertions land — test: `research-batch` output
      contains one such line per turn spent (→ scouting F24, F25, F26)
- [ ] The draw is seeded from `config.seed` so a batch run against an unchanged DB snapshot
      reproduces the same sequence of draws — test: two `research-batch` invocations against
      identical seed data produce identical draw sequences (→ scouting F21, decisions S1
      determinism precedent)
- [ ] Existing `research`, `research-status`, `bump-research-turns-budget`, and
      `backfill-research-turns-budget` commands are untouched and their tests pass
      unmodified (→ scouting F13, F14)

## Approach

- New pure function in `screen/score/` (sibling to `triage.py`/`boundary.py`): sums
  `stats_for_target(...).half_width * weight` across `config.dimension_weights` and
  `config.constraints`, with every constraint's weight set to
  `max(config.dimension_weights.values())` — a one-line policy constant, not a new
  `scoring.yaml` dial (→ scouting F17, F20, F21)
- `research_batch` replaces `_round_robin_pass` with a per-turn loop: each iteration loads
  every opening with remaining budget, computes its aggregate weight from
  `assertions_for_opening` + `dimension_rulings_for_opening` (mirroring
  `get_queue`'s per-opening assembly), draws one via `rng.choice(..., p=weights)` seeded
  from `config.seed`, and calls `_resume_opening(..., turns_requested=1)` (→ scouting F22)
- The RNG is constructed once per `research_batch` invocation (`np.random.default_rng(config
  .seed)`) and threaded through successive draws, not reseeded per turn — successive draws
  from one generator, matching `score()`'s existing seeding posture (→ scouting F21)
- The per-turn print is a `click.echo` call alongside the existing per-opening summary line,
  no new file/event/table; it can be silenced later by removing or flagging the echo, since
  nothing else reads it (→ scouting F23, F24, F25)
- Rank-before/after in the printed line is computed from the same aggregate-weight function,
  called once before the turn's `_resume_opening` and once after, over the same eligible-
  candidate set (→ scouting F26)

## Not Doing

- Pipeline-stage exclusion (`applied`/`closed` openings) from the eligible set — `Opening
  .stage` isn't implemented yet; this batch runs over the full backlog unconditionally, same
  deferral the rating bandit already made (→ scouting F9, F18)
- Any change to `select_primary_target`/`rank_targets` (the within-opening target choice) —
  this bearing picks *which opening*, not which target once there (→ scouting F3)
- A durable/persisted sampling log, or any new `ResearchTraceEvent` field — stdout only (→
  scouting F23, F25)
- `crossing_probability`/`standing`-boundary-based candidate filtering — the aggregate
  half-width signal is used directly, not gated by a separate contested-set check (→
  scouting F15, F17)
- Concentrating a whole batch on one top-ranked opening — every turn redraws (→ scouting F16)
- A web UI affordance to trigger a research batch and set its turn budget, and removing
  `bump-research-turns-budget`/`research-batch` as CLI commands once that affordance exists
  — explicitly deferred to a separate future bearing, not built here (→ scouting F27, F28,
  operator)

## Testing

Test-first by default. Exempt: nothing named at this level.

## Recalibrate When

- Real batch runs show the weighted draw concentrating so heavily on one or two openings
  that it behaves like the argmax approach the operator explicitly rejected — the weighting
  function (e.g. linear vs. squared half-width) needs revisiting
- The per-turn stdout trace turns out to be noise the operator ignores rather than reads —
  a signal to actually remove it, not just leave it silenced (→ scouting F25)
- The constraint-weight-as-max-dimension-weight heuristic visibly misranks openings once
  real data accumulates — promote it to a measured `scoring.yaml` dial instead (→ scouting
  F20)

## Agreed

- Weighted random sampling by aggregate half-width, resampled every turn, not argmax or
  round-robin — explicit operator reasoning: argmax risks wasting the whole budget on one
  opening's dead ends, and spreading turns serves the rating bandit's need for more grist
  across more openings (→ scouting F15, F16, F17, operator)
- Constraints weighted at the max dimension weight, not a new configured dial — acknowledges
  their measured dominance (F6) without adding an unmeasured knob (→ scouting F20, operator)
- Sampling trace is stdout-only, no new persistence — may be turned off later once the
  operator trusts the mechanism (→ scouting F23, F25, operator)
- Pipeline-stage filtering stays out of scope, inheriting the rating bandit's same deferral
  (→ scouting F9, F18, operator)
