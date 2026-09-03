---
feature: research-resumability
type: bearing
date: 2026-09-01
commit: 1fba424
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

Research is one-shot today: `intake <url>` fetches, identifies, runs one pass, and stops.
There is no way to see how many research turns an opening has spent against its budget, or
to manually run more against a specific opening or a batch. The operator wants to
steel-thread this before the algorithmic research bandit: give every opening a per-opening
turns budget (bumpable), and let the operator manually reconcile ("run 5 more turns for
Vetco") or run a fixed-size batch across whichever openings still have room. Terrain:
[scouting.md](./scouting.md).

## Done When

- [x] `intake <url>` runs its research pass against a `research_turns_budget` seeded from
      `scoring.yaml`, stored on the opening (→ scouting F23, F25)
- [x] Existing openings (already in the DB) can be backfilled with the same
      `scoring.yaml`-seeded budget (→ scouting F23)
- [x] The operator can bump one opening's `research_turns_budget` up (→ scouting F23)
- [x] A `research` CLI command can resume one opening and run up to N additional turns (or
      until its budget is reached), appending new events to the existing trace — test:
      second run produces strictly more `tavily_search`/`tavily_extract` events and new
      assertions for that opening, without re-extracting the original posting page (→
      scouting F1, F18)
- [x] A `research --batch N` command runs N additional turns across openings with budget
      remaining, resuming each from its trace and stopping when the batch or every
      opening's budget is exhausted (→ scouting F22)
- [x] A report/list command shows actual vs budgeted turns per opening, computed from the
      trace file (→ scouting F22)
- [x] The old per-pass env-var budgets (`SCREEN_SEARCH_BUDGET`, `SCREEN_TOKEN_BUDGET`) are
      replaced by the single turns budget (→ scouting F4, F17, F24)

## Approach

- One loop-running mechanism, parameterized by opening and turn limit: both `intake` and
  `research` construct `LoopState` from the existing trace + current assertions, run
  `dispatch`, and append events to the same trace file (→ scouting F15, F18)
- A **turn** = one budget-consuming research action: `tavily_search` or `tavily_extract`
  (excludes `decide_plan`/`stop`). Actual spend is computed by replaying the trace and
  counting those events — the trace stays the single source of truth (→ scouting F2, F3,
  F24)
- Replace `LoopState.search_budget` and `token_budget` with one `turn_budget` field; update
  the BAML research planner prompt and generated client accordingly (→ scouting F17, F24)
- One dial, no initial/lifetime split: `research_turns_budget` on `Opening`, seeded at
  intake (and backfillable for existing rows) from `scoring.yaml:research_turns_budget`.
  Intake spends against it directly; there is no separate smaller "initial" allocation (→
  scouting F25)
- Per-opening bump is a manual override on the stored `research_turns_budget` value — no
  formula, no heuristic (→ scouting F23)
- For the batch command, a simple deterministic fill: process openings with remaining
  budget in a stable order, one turn at a time, round-robin, until the batch or all budgets
  are exhausted. The algorithmic bandit replaces this allocator later (→ scouting F8, F22)
- The DB stores the trace pointer (already `Opening.research_trace_id`) and the per-opening
  budget; trace contents remain the JSONL blob on disk (→ scouting F13, F20)
- Refactor the CLI into a Click group with `intake` and `research` subcommands so both share
  the same loop-running code path (open space)

## Not Doing

- The algorithmic research-pass bandit that selects "which opening would benefit most" —
  this bearing supplies the substrate it will read; the bandit is a separate bearing (→
  scouting F8, F10, F22)
- Any heuristic that sets a per-opening budget from queue position — budget is one flat
  seeded dial plus manual bump; the heuristic belongs to the bandit-bearing (→ scouting F23)
- Token metering or token budgets (→ scouting F17)
- Per-event trace rows in the DB (→ scouting F20)
- Automatic periodic scheduling — triggers are manual CLI commands (→ scouting F22)
- Nomination-for-reopening routing (E5 contract) — unrelated to budget mechanics, still
  unbuilt (→ scouting F7)

## Testing

Test-first by default. Exempt: nothing named at this level.

## Recalibrate When

- The planner's coverage-based stop keeps firing before the turn budget is exhausted, so a
  resumed pass on an already-covered opening spends 0 turns and the batch stalls — the
  coverage stop and budget stop are pulling in different directions and the stop rule needs
  renegotiation (→ scouting F21)
- The simple round-robin batch allocator leaves the operator manually micro-managing which
  opening gets the next turn — a signal that the bandit-bearing should be picked up
- The flat seeded budget is so wrong that the operator bumps nearly every opening — then it
  is not a placeholder and needs a real per-opening starting point

## Agreed

- Split the work: this bearing is the resumability / turns-budget / manual reconciliation
  substrate; the algorithmic research-pass bandit is a separate, dependent bearing (→
  scouting F22, operator)
- One flat `scoring.yaml`-seeded turns budget per opening (used for both intake and later
  research), not separate initial/lifetime dials — simpler, no dial to keep in sync (→
  scouting F25, operator)
- Existing openings get the same seeded budget via backfill; any opening's budget can be
  manually bumped up (→ scouting F23, operator)
- Budget unit is turns (one `search` or `fetch` action), not tokens (→ scouting F24,
  operator)
- Trace stays a JSONL blob on disk, linked to its opening; no per-event DB rows (→ scouting
  F20, operator)
