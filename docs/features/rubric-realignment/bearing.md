---
feature: rubric-realignment
type: bearing
date: 2026-10-20
commit: 756fb40
parent: ./scouting.md
status: orienting
---

## Problem
The current rubric is not fully aligned with operator taste, especially on `location`, and threshold tuning alone is not recovering an acceptable precision/coverage tradeoff. We need to improve the rubric text itself, while keeping Jev as the evaluator and using the backtest to tell us whether a wording change actually helped.

## Done When
- [ ] We have a mismatch map for at least `location`, with recurring failure patterns grouped by rubric clause.
- [ ] We can point to the specific rubric lines that need clarification, splitting, or rewording.
- [ ] A before/after backtest shows whether the rubric edit improves the right bucket(s) instead of merely shifting errors around.
- [ ] We have a way to continue collecting operator signal while the system runs, so the rubric can keep improving even without a perfect gold set.
- [ ] The final change is committed as rubric text, not as an opaque prompt-optimization artifact.

## Approach
1. Start with `location`, because it already has a named mismatch pattern and the largest evidence set.
2. Use `scripts/backtest_jev_routing.py --show-mismatches` to inspect the mismatches that survive the current routing policy, then group them by rubric clause and by whether the failure is a false tie, false A, or false B.
3. Treat prompt-optimization frameworks as optional search tools later; the committed artifact is the rubric text, and Jev remains the evaluator.
4. If a mismatch turns out to be a data-shape issue or a missing operator preference rather than a wording problem, keep that separate from the rubric edit so we do not “fix” the wrong layer.

## Not Doing
- Shipping DSPy, TextGrad, or similar into production as the first move.
- Treating a framework search result as a substitute for understanding the rubric change it implies.
- Forcing every mismatch into a rubric edit if the real issue is missing data or a schema gap.
- Waiting for a perfect gold set before improving the rubric.

## Testing
- Run `scripts/backtest_jev_routing.py --show-mismatches` before and after each candidate rubric change.
- Compare mismatch counts and the tie/A/B error breakdown, not just aggregate precision.
- If the rubric text changes, rerun the relevant target-specific checks rather than assuming the effect is local.

## Recalibrate When
- A rubric edit improves `location` but degrades `compensation` or another important target enough to matter.
- The same error pattern repeats after a wording change, which suggests missing operator data rather than a wording defect.
- A search framework finds a promising variant, but we cannot explain the improvement in rubric language.

## Agreed
- The rubric is the thing to improve.
- Jev is still the evaluator.
- Any framework we adopt later is a search aid, not the product shape.
- We will keep collecting better operator data while the system runs, instead of assuming the current corpus is a complete gold set.
