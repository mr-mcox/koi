---
feature: guarded-scoring
type: bearing
date: 2026-10-22
commit: e7f39d8
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

Openings the operator rejects on a dealbreaker dimension (TRM on mission, Rula on craft)
rank in the top 5, because a linear weight rewards upside exactly as hard as it punishes
downside, and location/culture upside at weights 6/4 buys back any mission or craft loss.
Make dealbreaker dimensions bite on the downside and only nudge on the upside, without
starving the bottom of the pool. Terrain: [scouting.md](./scouting.md)

## Done When
- [ ] decisions.md has a new S-entry superseding S12's linear-only shape and amending S1
      for the queue, carrying its rejections → `grep -n "^### S16" docs/architecture/decisions.md`
- [ ] On a copy of the live DB, the F4 seven are in the top 10 and TRM, Rula Provider,
      Affirm are not → **needs you**: review the before/after table I produce. **Pause here.**
- [ ] Research draws and compare-picker pairs read a guards-off P(top-K): an opening with
      an unexamined guarded dimension gets more attention than its queue rank alone would
      give → `tests/test_bandit.py`, `tests/test_compare_picker.py`
- [ ] No screening opening has zero attention weight → `tests/test_bandit.py`
- [ ] `uv run python scripts/check.py` passes

## Approach

- A guard is a sign-dependent transform on each sampled draw inside `rank_pool`'s rollup,
  before weighting: below Mixed × downside, above × upside (→ scouting F8, F9, F10)
- Guard membership is a boolean beside `weight` in `rubric.yaml`; the curve is one shared
  `(downside, upside)` pair in `scoring.yaml`, not per-dimension (→ scouting F4, F21)
- The queue sorts on the guarded rank only. Attention (research draws, compare picker)
  reads a guards-off P(top-K) computed from the same joint draw, so the two views can't
  disagree because of sampling noise (→ scouting F8, F11, F26)
- The attention floor lives in `boundary_weight`, a named dial in `scoring.yaml`, so both
  attention consumers inherit it (→ scouting F12, F25)
- The guard flag is not rendered into rubric prompt text; Jev and research see only the
  weight change (→ scouting F18, F19)

## Not Doing

- Re-admitting Jev-ruled pairs to the picker — working as designed (→ scouting F17)
- Curves on craft or any unguarded dimension; per-dimension curve parameters — no rank
  change measured (→ scouting F4)
- Margin-bearing comparisons, overall A-vs-B rulings to fit weights, beta changes — later
- Overriding TRM's Jev rulings — the operator does that in the UI

## Testing

Test-first by default. Exempt: nothing.

## Recalibrate When

- If the live-copy review fails the F4 expectation, stop before any attention change.
- If keeping both views from one draw adds more than 25% to `rank_pool` wall time, stop.
- If the kill test passes only by changing its threshold or `top_k`, stop.
- If guards need changes to `compare.py`'s fit or the picker's `_overall_diff`, stop.
- If the first compare session after the attention change mostly offers pairs from the
  queue's bottom third, stop and revisit the floor (→ scouting F25).

## Agreed

- Guards on location, mission, schematic, internal_culture; craft linear, not curved — a
  craft curve moved nothing (→ scouting F4, F5)
- Weights on a 1/2/3 scale, not up to 6 (→ scouting F6, F7)
- One shared curve (×3 down, ×0.3 up), not per-dimension — top 7 robust to the curve
  (→ scouting F4)
- Guard applied per sample, not to the estimate alone — estimate-only turned unknowns
  into lottery tickets (→ scouting F9)
- The queue gives up favoring the wide unknown; attention keeps it (→ scouting F8)
- Jev-ruled pairs stay out of the picker (→ scouting F17)
- `top_k` 10, not 5 (→ scouting F15)
- Pause for operator review after guarded ranking, before attention changes (→ scouting F24)
