---
feature: rubric-recalibration
type: bearing
date: 2026-10-20
commit: bbb6a14
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

The operator wants to score for a while, then let a loop run several rounds unattended —
trying edits, measuring them, forming theories about what to try next — and come back to a
reviewable diff. Today the equivalent is a human reading mismatches by hand, which found
one real `location` defect and several false leads. Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] `scripts/recalibrate_rubric.py --target <slug>` runs N rounds unattended and prints,
      per round: the candidate edit, held-out bucket deltas, and the theory it drew
      → run on `location`; output names every case used and every round's result
- [ ] A round's result visibly informs the next round's candidate, rather than N
      independent draws → the round-2 prompt contains round-1's measured outcome
- [ ] A target under 70 usable pairs exits with the shortfall and proposes nothing
      → run on `trajectory` (n=9); non-zero exit, no candidate
- [ ] A candidate measured as no better than baseline is reported as "no edit proposed"
      and the rubric is left at its starting text → force with a fake proposer returning a
      no-op edit
- [ ] A run ends with its best candidate left applied in the working tree, uncommitted,
      and the round log naming what else was tried; held-out is reported but does not veto
      the winner → `git diff rubric.yaml` after a run
- [ ] Candidate text passes `tests/test_rubric.py`'s structural and privacy assertions
      before being applied → a candidate containing a salary figure is rejected in-loop

## Approach

- Build on `backtest_jev_routing.py`'s loaders and `load_scoring_config`, not a parallel
  evaluation path (→ scouting F10)
- The proposer is an LLM call reading labeled cases; no keyword mining, no clustering
  (→ scouting F6)
- Rounds are sequential and few, each seeing prior rounds' candidates and measured
  results; no beam or population search (→ scouting F9, F22)
- The loop mutates the working-tree `rubric.yaml` directly; no isolated path, no
  crash-restore machinery (→ scouting F23)
- Each pair is evaluated in both orders and the probabilities averaged, so order can't
  confound a candidate comparison (→ scouting F19)
- Split eligible pairs 80/20 into propose/held-out; candidates are chosen on the propose
  split, and held-out is a readout for overfit rather than a gate (→ scouting F14)
- Output is a diff plus the round log; `git` is the accept/reject surface
  (→ scouting F11, F16)
- Candidate text is validated against `tests/test_rubric.py`'s assertions before use
  (→ scouting F12)

## Not Doing

- Committing anything, ever — the operator reviews and commits (→ scouting F22)
- A review UI, a diff database, or a recalibration-run data model — git already holds this
- Adopting DSPy/TextGrad/an autoresearch harness; the loop is ~100 lines against the
  existing backtest (→ scouting F7)
- Claiming an edit improves extraction or classification — only the verdict stage is
  measured (→ scouting F8)
- Treating discrete outcome flips as an instability signal — they're boundary artifacts of
  `route_verdict`, not evaluator noise (→ scouting F18)

## Testing

Test-first by default. Exempt:
- the LLM proposer call — paid API, injected via a Protocol like `JevVerdictProvider` so
  round sequencing and restore-on-crash are tested with a fake returning canned candidates

## Recalibrate When

- A target's forward accuracy sits at chance (~33%) — the rubric or the digest is wrong at
  a level wording can't reach, and the loop should say so rather than propose
  (→ scouting F20, F15)
- The held-out readout diverges materially from the training win for two rounds in a row —
  the loop is overfitting and should surface that rather than hiding it (→ scouting F14)
- Proposals start needing the full rubric rather than one dimension's text (→ scouting F8)

## Agreed

- Targets are admitted by measured buckets and accuracy, not by how often the
  operator feels bothered — `compensation` felt worst and was a missing-input bug
  (→ scouting F5, F4)
- Eligibility floor is 70 usable pairs, ratchetable; counted on usable, not raw
  (→ scouting F21, F2)
- `location` is the first target — it clears the 70 floor and has hand-found candidates the
  loop's output can be checked against (→ scouting F21, F24)
- The loop may apply edits and iterate unattended; it may never commit (→ scouting F22)
- Order-averaging is worth 2× Jev calls per pair — it removes a measured systematic bias
  rather than a hypothesised one (→ scouting F19)
- "No edit proposed" is a successful outcome, not a failed run (→ scouting F15)
