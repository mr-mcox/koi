---
feature: few-shot-calibration
type: scouting
date: 2026-10-20
commit: ce36905
---

## What We're Doing

Encapsulate my taste so the easy cases — especially compensation and location — need less of my attention, while mission and craft_direction stay live enough for me to review. Test whether smarter few-shot selection, and later rubric tuning if needed, can improve alignment without hurting the overall set of decisions.

## Findings

- **F1** — `scripts/calibrate_few_shot.py:46-60,184-244` — there is already an offline calibration harness that loads operator comparisons from SQLite, splits them into test/validation/search pools, and compares random, stratified, and searched few-shot policies while reporting accuracy and average confidence.
- **F2** — `src/screen/verdict/few_shot.py:14-37` — the current few-shot baseline is a random subset of eligible operator rulings; if there are more than `max_examples`, the harness samples without any notion of boundary cases or target-specific policy.
- **F3** — `src/screen/extract/prompt.py:63-96`, `src/screen/verdict/jev_assertion_classifier.py:49-85`, `src/screen/verdict/jev_verdict_provider.py:44-70` — the same rubric text feeds both assertion classification and pairwise verdicting, so any rubric edit affects both stages at once.
- **F4** — `docs/architecture/README.md:26-27` and `docs/architecture/decisions.md:385-387` (R4) — rubric text is load-bearing and versioned; every change is supposed to carry a reason, not silently drift.
- **F5** — operator — compensation and location are the “easy ones” they want to spend less time on; craft_direction and mission still merit review, schematic is often binary, and internal_culture is usually only yellow-flagged or indeterminate.
- **F6** — operator / in-session analysis — the live DB has enough operator comparisons to support per-dimension policy comparisons before changing production behavior.

