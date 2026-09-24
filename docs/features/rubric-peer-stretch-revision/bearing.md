---
feature: rubric-peer-stretch-revision
type: bearing
date: 2026-09-24
commit: 531ee63
branch: main
status: decomposed
scouting: ./scouting.md
---

## Problem

`peer` scores public evidence that the operator says isn't the real signal — peer quality
needs interview/conversation history, out of scope for web research. `stretch` currently scores
ability-distance from the operator's level (inverted-U, seniority-keyed); the operator's live
corpus shows this barely discriminates (89 Strong / 3 Mixed / 0 Poor) and doesn't match how they
actually use the concept — a discipline-preference axis. Terrain:
[scouting.md](./scouting.md).

## Done When

- [ ] drop-peer done: `peer` is gone from `rubric.yaml`, `src/screen/types.py`, and the BAML
      `Assertion` target enum; `check.py` passes with no `peer` references.
- [ ] redefine-stretch done: `stretch` is renamed and redefined as a discipline-preference
      ladder per the operator's three tiers; the decision log records the superseded R1.

## Approach

- Decompose into two independently reviewable children: one to drop `peer`, one to redefine
  `stretch` with a new slug. `(open space)` on ordering — they don't depend on each other; the
  decision-log entry can be written in whichever lands last.
- Common outcome: update `docs/architecture/decisions.md` with R-entries recording what each
  change supersedes (`peer` → R5; `stretch` → R1). Both children share this criterion.

## Not Doing

- No override-likelihood signal in the scorer — F14 is a separate design question, not a
  rubric wording change.
- No new dimension for OQ16's "software is core to strategy" half — `peer` was carrying it,
  now it's unhomed again, but that's already a tracked open question.

## Testing

Test-first by default. Exempt: `rubric.yaml`, `docs/architecture/*.md` — prose/config.

## Recalibrate When

- If removing `peer`/renaming `stretch` breaks a test asserting dimension list count/names,
  update the test as part of the change, not as a regression.

## Agreed

- Drop `peer` entirely, no replacement dimension — operator (→ scouting F3).
- Redefine (not recalibrate) `stretch` and rename the slug so old assertions don't get silently
  reinterpreted — operator + F9 (→ scouting F8, F9).
