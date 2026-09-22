---
feature: pairwise-ranking
type: bearing
date: 2026-09-19
commit: 2ba9832
branch: rank-pool
status: completed
parent: ./bearing.md
scouting: ./constraints-and-rubric-scouting.md
---

## Problem

Constraints scored as multiplicative tolerability factors made sense when the queue sorted
on `P(overall > bar)`, but in a rank-based queue the same practical outcome — bad cases
miss the top 5 — can be achieved by an additive dimension with sufficient weight. The
operator wants the simpler model: no special-case constraint family, no situation labels, no
separate tolerability range machinery. Former constraints become dimensions; a new
`distributed` dimension captures the location-quality ordering; compensation is reframed.
Terrain: [constraints-and-rubric-scouting.md](./constraints-and-rubric-scouting.md).

## Done When

- [x] `rubric.yaml` has no `constraints:` section; former constraints and `distributed`
      are ordinary dimensions with weights → `tests/test_rubric.py`
- [x] `src/screen/score/` contains no `ConstraintRange`, `_sample_constraint`,
      `_map_to_range`, or constraint multiplication; `overall` is a weighted dimension sum
      only → grep `src/screen/score/`
- [x] `screen.types.Target` and the BAML schema list only dimension/non-scoring slugs →
      `test_rubric_slugs_match_target_literal`
- [x] A high-weight dimension with `Poor` assertions sinks an otherwise-best opening out of
      top 5 → `tests/test_scorer.py`
- [x] Compensation's definition asks "would total compensation likely be higher than
      baseline," not a flat band comparison, while `SCREEN_COMPENSATION_BASELINE` never
      appears in a committed file → `test_rubric_compensation_dimension_has_no_baseline_number`
- [x] `docs/architecture/decisions.md` S2 is superseded (S12) and R3 is superseded (R6);
      `domain-model.md`'s Scorer section no longer describes a separate constraint path →
      grep for S12 and R6

## Approach

- Retire the `ConstraintRange` dataclass, constraint loading in `loader.py`, and the
  multiplicative constraint step in `rank_pool`; dimensions become the only scored target
  family (→ scouting F3, F4, F5)
- Move the three former constraints into `rubric.yaml`'s `dimensions:` section with weights
  reflecting their practical importance; `distributed` is added at weight 5 (→ scouting F6,
  F7)
- Keep `Fit` (Poor/Mixed/Strong) as the single assertion vocabulary for all dimensions,
  including the former constraints and compensation; no situation-label field is added (→
  scouting F8)
- Rewrite compensation's rubric definition and fit anchors to the operator's reframing
  without exposing the baseline number (→ scouting F9)
- Hand-sync new slugs across `rubric.yaml`, `screen.types.Target`, and BAML's closed
  vocabulary (→ scouting F10)

## Not Doing

- Situation labels or a constraint-specific extraction vocabulary — rejected in favor of the
  simpler dimension model (→ scouting §Rejected alternative)
- A separate "kill-only" location constraint paired with `distributed` — `distributed`
  alone carries the ordering (→ scouting F7)
- Converting or migrating the 107 historical constraint assertions (→ scouting F12)
- Generating `Target`/BAML schema from `rubric.yaml` (open-questions OQ13) — hand-sync one
  more time

## Testing

Test-first by default. Exempt: nothing named yet.

## Recalibrate When

- If a high-weight dimension fails to reliably push a clear mismatch out of the top 5,
  stop and revisit whether the weight is high enough or whether a second scoring family is
  actually needed (→ scouting F1, F2).
- If rewriting compensation's definition reveals the private baseline needs to enter
  extraction logic rather than just runtime config, stop — that leaks into committed files
  (→ decisions.md D23, AGENTS.md §Privacy).

## Agreed

- Constraints retire as a target family; all scored targets are dimensions with weights (→
  operator, scouting F1, F2)
- `distributed` is weight 5 and captures the full location-quality ordering without a
  paired kill-only constraint (→ parent scouting F59, F62, F77, F84; scouting F7)
- Compensation is reframed as a likelihood-of-higher-total-compensation dimension, with the
  baseline still private config (→ parent scouting F71; scouting F9)
- Historical constraint assertions are not migrated or treated as unexamined (→ scouting F12)

## Amendment (2026-09-19, same session)

Operator merged `distributed` into `location` after this bearing landed: the two ladders
covaried (remote-first ⇒ trivially workable; forced-relocation ⇒ not remote at all), so one
severity ladder replaces both, kept under the `location` slug at weight 6 (not summed to 11)
so existing `location` assertions need no migration → decisions.md S13 (supersedes the
`distributed` half of S12).
