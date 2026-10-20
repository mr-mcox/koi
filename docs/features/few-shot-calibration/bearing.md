---
feature: few-shot-calibration
type: bearing
date: 2026-10-20
commit: ce36905
branch: main
status: done
scouting: ./scouting.md
---

## Problem

The operator wants their taste encapsulated so the easy calls — especially compensation and location — stop consuming so much attention, while mission and craft_direction remain live enough to review. We have enough evidence to test whether the lever is better few-shot selection, rubric wording, or both, but we should separate those questions instead of collapsing them into one implementation choice. [Terrain: scouting.md](./scouting.md)

## Done When

- [x] `scripts/calibrate_few_shot.py` can run against the live SQLite DB and report per-target validation/test accuracy plus average confidence for random, stratified, and searched few-shot policies.
- [x] The harness identifies which dimensions are most worth automating first, without changing production ranking behavior.
- [x] We have a clear answer on whether better example selection is enough before we touch rubric text.

## Approach

- Keep the first feature as an offline calibration harness over the live DB, with held-out validation/test splits and explicit comparison of random, stratified, and searched policies (→ scouting F1, F6).
- Use the same production rubric text and the same Jev adapters in the harness, so any measured gain applies to the real assertion-classification and verdict paths, not a toy surrogate (→ scouting F3).
- Treat rubric tuning as a second-stage decision, after the harness shows where policy selection is enough and where wording changes are actually needed; do not mix calibration-engine changes with rubric edits in the same pass (→ scouting F3, F4).
- Start by measuring the dimensions the operator wants to offload first — compensation and location — while keeping mission and craft_direction as the live judgment cases that still merit review (→ scouting F5).

## Not Doing

- Wiring DSPy into production before the harness proves we need it — the first question is whether the current few-shot path can be improved materially at all (open space).
- Changing live ranking behavior or rubric text as part of the first calibration pass — this phase is for measurement and comparison, not policy rollout (→ scouting F4).
- Turning the harness into a general experimentation framework yet — we only need enough structure to answer the few-shot/rubric question now (open space).

## Testing

- `scripts/calibrate_few_shot.py` — manual smoke runs against `data/live/screen.db` are the acceptance check for this orienting phase; formal tests can follow once the policy shape settles.

## Recalibrate When

- Validation and test diverge sharply, or confidence rises without a matching accuracy gain — the search policy is overfitting or miscalibrated.
- Compensation and location are not materially easier to automate than mission/craft_direction after the first pass — the prioritization is wrong.
- A rubric edit improves one target while degrading the others enough to matter — split the calibration-engine question from the wording question more explicitly.

## Agreed

- Build the scouting/bearing split first, not a DSPy-first implementation — we need the measurement frame before choosing the optimizer (→ scouting F1, F3, F4).
- Keep the work read-only until the eval tells us what to change in production — the first deliverable is an answer, not a rollout (→ scouting F1, F4).
