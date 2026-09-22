---
feature: pairwise-ranking
type: scouting
date: 2026-09-19
commit: 2ba9832
parent: ./bearing.md
---

## What We're Doing

bearing.md's fourth Done When item originally targeted constraints scoring from situation
labels plus a new `distributed` dimension. After drafting that bearing, the operator rejected
keeping constraints as a separate target family: in a rank-based queue where only the top 5
matter, an additive dimension with sufficient weight can push bad cases out of the top K
without the maintenance burden of a multiplicative tolerability path. This scouts the
simplified replacement: **former constraints become dimensions; `distributed` is a new
weighted dimension; compensation is rewritten as a dimension.**

## Findings

- **F1** — operator (this conversation) — constraints are not worth a separate scoring family.
  A high-weight dimension that drags an opening's overall score down achieves the same
  practical outcome (it doesn't reach top 5) with less special-casing.
- **F2** — `docs/architecture/prototype-decisions.md` D7 — the original "constraints are
  discount factors, not gates" decision was justified by the bar-crossing model: to drag a
  perfect company below neutral via additive weight, location would have to outweigh all
  seven dimensions combined. That argument depended on `P(overall > bar)` and a neutral
  threshold; rank-based sorting (`P(rank ≤ top_k)`) only needs the bad case to sit below the
  5th-best opening, so a moderate weight suffices. The decision is now open to supersession.
- **F3** — `src/screen/score/scorer.py:80-87` (`_sample_constraint`), `scorer.py:71-77`
  (`_map_to_range`), `src/screen/score/types.py` (`ConstraintRange`),
  `src/screen/score/loader.py:36-45` (`_constraint_range`) — the constraint-specific scoring
  machinery can be removed entirely if constraints become dimensions.
- **F4** — `src/screen/score/scorer.py:94-98` (`stats_for_target`), `scorer.py:134-172`
  (`_deterministic_quality`), `scorer.py:174-189` (`rank_pool` dimension loop) — dimensions
  already use the same `TargetStats` shrinkage and weighted-sum machinery for every target;
  adding three more dimension slugs and removing constraint multiplication is a structural
  simplification, not a parallel path.
- **F5** — `src/screen/score/scorer.py:190-200` — the multiplicative constraint factor is the
  only place `overall` is rescaled after the weighted quality sum. Removing it means
  `overall` is just the weighted sum (clipped to [0, 1]), the same shape as the old per-opening
  `score()` quality but now pool-scoped.
- **F6** — `rubric.yaml:26-93` — the existing `constraints:` section (location,
  internal_culture, extractive_business) moves into `dimensions:` with weights. The
  per-situation tolerability ranges and "Not examined" labels are retired along with the
  constraint concept.
- **F7** — parent scouting F59, F62, F77 — `distributed` stays a new dimension (weight 5),
  but it is no longer paired with a separate kill-only `location` constraint. The
  gradations (fully remote company > remote with travel acknowledged > remote silent >
  central office hiring remote > hybrid) become fit anchors on the `distributed` dimension
  itself.
- **F8** — `src/screen/types.py:119` (`Fit` Literal), `src/screen/baml_src/extract.baml:20-26` —
  the `Fit` vocabulary (Poor / Mixed / Strong) applies to all dimensions, including the former
  constraints. No new situation-label field is needed.
- **F9** — parent scouting F71, `docs/architecture/prototype-decisions.md` D8, decisions.md
  R3 — compensation stays a dimension but its definition should be rewritten to match the
  operator's actual judgment: "would total compensation likely be higher than baseline," with
  the baseline still private config. The `Fit` anchors become that framing instead of a flat
  Poor/Mixed/Strong band.
- **F10** — `tests/test_rubric.py` — the rubric-sync tests still apply; every new dimension
  slug must appear in `screen.types.Target` and the BAML schema's closed vocabulary, same as
  any prior rubric change.
- **F11** — `tests/test_scorer.py` — tests covering `_sample_constraint`, `_map_to_range`,
  and constraint-kill behavior become invalid and are removed; tests covering
  dimension-kill behavior (a low mean on a high-weight dimension sinks an opening) replace
  them.
- **F12** [!] — `data/live/screen.db` has 107 existing constraint assertions
  (location/internal_culture/extractive_business) carrying `Fit` values. Under the new
  model they become ordinary dimension assertions and score exactly like any other dimension
  assertion. No migration or conversion is required, and they are not treated as unexamined.
  This is simpler than the rejected label path, but it means historical location assertions
  may score differently than under the old constraint model.

## Rejected alternative

- Keeping constraints as a separate target family with situation labels
  (`constraints-and-rubric.md` prior draft, now discarded). Reason: operator preference for
  simplicity and the rank-based context undermining D7's original measured justification.
