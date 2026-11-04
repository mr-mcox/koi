---
feature: research-target-opportunity
type: bearing
date: 2026-11-04
commit: aa6b3ab
branch: main
status: orienting
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

The Surveyor-framing comparison (search-ready question vs. hypothesis-first vs.
gap-description) was spiked live and came back undiscriminating: dimension choice
converged to `craft_direction` in 11/12 calls and the navigator's first action was
near-identical across all three framings (→ scouting F45). The cause traced to the
navigator itself, not the Surveyor — it has no visibility into assertion content
(→ scouting F36-F39), which `navigator-context.md` is fixing. This bearing picks the
comparison back up once that lands, so the framing decision is judged by a navigator that
can actually act on the differences. Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] `navigator-context.md` is `done` → read its status
- [ ] The three framings from `scratch/research-target-opportunity/survey_spike_compare.py`
      are re-run against the same 4 scenarios with the context-aware navigator, and their
      actions across a full multi-turn pass (not just turn 1) are compared
      → **needs you**: read the re-run output
- [ ] One framing is chosen and written into `survey.baml`'s prompt → scouting entry
      recording the choice and what it rules out
- [ ] `uv run python scripts/check.py` passes

## Approach

- Reuse `scratch/research-target-opportunity/` as the starting point, not a rewrite — the
  scenario-mining and pseudonymization logic doesn't change (→ scratch/README.md)
- Extend the comparison past turn 1: run each framing through several `DecidePlan` turns
  (synthetic or replayed search/fetch results) so divergence that only shows up after the
  first search is visible (→ scouting F45)
- (open space) — everything else about how the multi-turn comparison is built

## Not Doing

- Starting this before `navigator-context.md` is `done` — the spike that motivated it
  explicitly found the comparison undiscriminating without that fix (→ scouting F45)
- Changing model tier as part of this comparison — a separate, later question
  (→ scouting F44)

## Testing

Spike work against `scratch/` — not test-first, not part of `check.py` (→ parent
`navigator-context.md` §Testing, same exemption class).

## Recalibrate When

- If the context fix alone resolves the redundancy problem (F37's near-duplicate rate) and
  all three framings still converge, stop: the framing choice may not matter at this model
  tier, and F44 (model tier) becomes the live question before framing does.

## Agreed

- Parked until `navigator-context.md` is `done`, not run in parallel — the pre-fix spike
  showed the comparison can't discriminate while the navigator is context-starved
  (→ scouting F45)
- The spike scripts move to `scratch/` (gitignored), not deleted — they're resumed here,
  not thrown away (→ operator)
