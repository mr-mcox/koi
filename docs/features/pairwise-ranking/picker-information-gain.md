---
feature: pairwise-ranking
type: bearing
date: 2026-09-18
commit: PENDING_COMMIT
branch: main
status: completed
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

`select_comparison`'s score (`weight * (0.5 - abs(p - 0.5))`) is maximized exactly when
the model believes a pair is a dead-even tie. A `tie` outcome pushes the fitted mean
difference toward zero, which pushes `p` toward exactly 0.5 — the highest score the
metric can produce. The result: judging a pair as a tie doesn't lower its priority, it
raises it to the ceiling, and the same pair/dimension gets re-suggested forever (observed
live: `staff-software-engineer-distributed-systems-787e24` vs
`staff-software-engineer-full-stack-4011a5` on `stretch`, six ties in a row,
`predicted_a_beats_b = 0.5` every time). The posterior itself is fine — `fit_pairwise`
genuinely shrinks `var_diff` with each tie — the picker's score just never looks at that
shrinking variance, only at the point estimate. A first attempt at
`score * var_diff` broke a different, already-correct behavior: `domain` was exempt from
needing assertions (scouting F36→F71) purely as a *picker* workaround, so it always
carried the *widest possible prior* variance in that formula, and raw variance-weighting
made the picker prefer asking about `domain` over a dimension with eight converging
assertions, even though `domain` has the lowest rubric weight (1 vs. `stretch`/`schematic`'s
3). Investigating that exposed the exemption itself as unnecessary: research already
covers `domain` on the same uncertainty-ranked footing as every other dimension
(`all_dimension_slugs()` feeds `LoopState.targets`; live data confirms 27/31 screening
openings already have a real `domain` assertion). The exemption was bypassing the
evidence check even where real evidence existed, forcing a permanent `n=0` prior that had
nothing to do with the actual state of research. This bearing supersedes the parent's Not
Doing item "Expected-information-gain pair selection — only if the simple picker asks
poor questions" (scouting F29): the picker asks poor questions now, confirmed on live
data (F30 also names this shape: dimension choice by variance share, with a tie shrinking
that dimension's share so the next question moves on — that's the same fix scoped one
level down, to the pair inside a dimension rather than across dimensions).

## Done When

- [x] A pair/dimension that has accumulated several tie outcomes drops in selection
      priority below a fresh, unexamined pair on the same dimension, even though both
      have `p ≈ 0.5` → `test_repeated_tie_drops_pair_below_a_fresh_pair`
- [x] `domain`'s prior variance is derived the same way as every other dimension — no
      permanently-wide special case → `test_domain_prior_variance_matches_any_other_dimension`
- [x] The information-gain metric is expressed as a reduction relative to each pair's own
      prior uncertainty (a shrinkage ratio), not raw absolute variance, so structurally
      different prior widths don't win by construction → same tests above
- [x] Existing picker tests continue to pass without weakening their assertions

## Approach

- Score by expected reduction in `var_diff`, normalized against that pair's own prior
  `var_diff` (before any comparisons): `weight * (0.5 - abs(p - 0.5)) * (var_diff /
  prior_var_diff)`. The ratio is 1.0 for an untouched pair (no discount) and shrinks
  toward 0 as comparisons accumulate on that specific pair.
- New `_prior_variance` helper computes a single opening's prior variance on a target
  directly from `stats_for_target`, independent of any comparison evidence — reused by
  `_best_pair_for_dimension` for both sides of the pair to build `prior_var_diff`.
- Dropped `domain`'s exemption in `_qualify_for_dimension` (`if target == "domain":
  return list(opening_ids)`). It was a workaround for an assumption — that `domain`
  structurally lacks evidence — that live data contradicts: research already covers
  `domain` on the same footing as every other dimension (`all_dimension_slugs()` feeds
  `LoopState.targets`), so `domain` now qualifies for a pair exactly like `stretch` does:
  at least one effective assertion on each side. This is what actually fixes the
  domain-out-scores-everything failure — the shrinkage ratio alone wasn't enough while
  the exemption kept forcing `domain`'s prior to `n=0` regardless of real evidence.
- Contained to `src/screen/score/compare_picker.py`: `_qualify_for_dimension` loses its
  domain branch, `_best_pair_for_dimension` gains the prior-variance lookup and the
  ratio in its score expression. `_dimension_posterior`'s signature and
  `select_comparison`'s public contract are unchanged.

## Not Doing

- Changing how `tie`/win outcomes update the posterior (`fit_pairwise`, `Comparison`) —
  that math is already correct; only the *selection* score was blind to it.
- A cooldown/exclusion list keyed on recently-suggested pairs — the shrinkage-ratio fix
  makes that unnecessary; a pair that's been asked about enough naturally scores low.
- Seeding synthetic/default assertions for any dimension — rejected explicitly for
  `domain` (operator: "I don't want anything made up"); every dimension's evidence comes
  from an actual research pass or stays absent until one runs.
- Cross-dimension weighting beyond rubric weight (scouting F30's variance-share framing)
  — this bearing only fixes the within-dimension pair pick; the parent's dimension-choice
  question is Not Doing here unless the live symptom reappears one level up.

## Testing

Test-first by default. Exempt: nothing at this level.

## Recalibrate When

- If the shrinkage ratio still lets a stuck pair dominate after a handful of ties in a
  reproduction test, stop — the metric needs a different shape, not a coefficient tweak.
- If fixing this exposes the same "wide-prior dimension always wins" failure mode at the
  cross-dimension level (scouting F30), stop and treat dimension choice as in scope too
  rather than patching around it here.

## Agreed

- Normalize by each pair's own prior variance (a shrinkage ratio), not raw absolute
  variance — keeps a structurally wide prior from winning by construction (→ operator,
  corrects the naive `* var_diff` attempt).
- Drop `domain`'s picker exemption rather than special-casing around it — research
  already backfills `domain` like any other dimension, so the exemption was solving a
  problem that no longer exists, and no synthetic/default assertion is needed to close
  the gap (→ operator: "it can be empty and there should be something structural that
  causes it to be researched later" — that structural path, `all_dimension_slugs()` →
  `LoopState.targets`, already existed).
