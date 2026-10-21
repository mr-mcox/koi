---
feature: full-context-sonnet-baseline
type: bearing
date: 2026-10-21
commit: 67a04cb
branch: main
status: orienting
scouting: ./scouting.md
---

## Problem

Before adding Jev-powered retrieval, test the simpler hypothesis: can Sonnet do better if it sees the whole propose-split context for a target, rather than a routed packet? The point is to learn whether retrieval is buying accuracy or just saving tokens / prompt space. Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] A full-context run on `location` prints the proposer's theory, train buckets, and held-out buckets with no retrieval layer in the middle → run the existing recalibration command in full-context mode and inspect the log
- [ ] The comparison between sampled context and full context is visible in the run output, so the operator can tell whether the simpler baseline was good enough → run both modes on the same target and compare the printed train/held-out buckets
- [ ] The baseline can be repeated on a second eligible target without changing the loop shape → run it on `compensation` as a second check
- [ ] If full context is not better, the output makes that failure legible enough to justify the later retrieval spike → a run that underperforms the sampled prompt still names the theory and bucket deltas clearly

## Approach

- Feed the proposer the whole propose-split context for the target before any retrieval machinery exists; do not invent a packet schema yet (→ scouting F1, F3)
- Keep the rest of the recalibration loop unchanged: same objective, same train/held-out split, same reporting, so this isolates the prompt-shape effect (→ scouting F2, F4)
- Compare full-context and sampled-context runs on the same eligible target before deciding whether Jev retrieval is worth the added complexity (→ scouting F6, F5)

## Not Doing

- Jev reranking, packet balancing, or any example-selection schema — those remain the later candidate if the baseline fails (→ scouting F3, F6)
- Changing the objective function again in this feature — the question here is prompt context, not search policy (→ scouting F2)
- Rewriting the rubric or the scoring core as part of the experiment — this is a prompt-shape spike only (→ scouting F4)

## Testing

Test-first by default. Exempt:
- none

## Recalibrate When

- Full-context Sonnet still produces vague theories or no candidate on `location` — retrieval may be worth the added machinery
- The output becomes too long or noisy to review — then the baseline itself is failing as a product shape, not just as a model setting
- A second target behaves differently enough that the answer depends on target shape rather than context shape — the feature should then say so explicitly before more work is added

## Agreed

- The first question is whether retrieval helps accuracy, not whether it helps cost or elegance — the baseline comes first (→ scouting F1, F6)
- The rest of the loop should stay fixed while the prompt shape is tested — isolate one variable at a time (→ scouting F2, F4)
- Jev retrieval is deferred until the simpler Sonnet baseline has been shown to be insufficient or materially worse (→ scouting F3)
