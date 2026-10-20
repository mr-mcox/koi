---
feature: rubric-realignment
type: scouting
date: 2026-10-20
commit: 756fb40
---

## What We're Doing
Investigate the mismatches, starting with `location`, to find rubric clauses that misstate operator taste. This is about changing the rubric text itself, not adding a prompt-optimization framework in the product. The target is to make the rubric say what the operator actually means, then re-measure with Jev as the evaluator.

## Findings
- **F1** — `scripts/backtest_jev_routing.py` — threshold tuning alone does not get us to a comfortable operating point. In the current backtest, the best precision in the asymmetric sweep is still only in the mid-60s, and it comes with very low coverage. That says the signal is real but not yet strong enough.
- **F2** — `docs/architecture/README.md:26-27`, `src/screen/extract/prompt.py:63-96`, `src/screen/verdict/jev_assertion_classifier.py:49-85`, `src/screen/verdict/jev_verdict_provider.py:44-70` — rubric text is load-bearing and shared across extraction, classification, and verdicting. A rubric edit changes more than one stage, so it is a high-leverage move and must be made deliberately.
- **F3** — operator observation from the current `location` review — “silent on travel” currently behaves like remote in practice, which means the written rubric and the operator’s taste are not aligned on that clause.
- **F4** — `docs/architecture/learnings.md:102-115` — the prototype already found evidence that the rubric is near its encodable limit in some areas; accumulated cases sometimes matter more than better wording. That means rubric work is worth doing, but we should expect some mismatches to be “needs more operator data,” not just “needs a better sentence.”
- **F5** — live-data coverage is uneven — some targets have enough comparisons to inspect patterns, but the corpus is not a gold set. We should expect to keep learning from live use while improving the rubric, not wait for a perfect offline dataset.
