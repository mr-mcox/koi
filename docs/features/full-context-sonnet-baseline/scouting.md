---
feature: full-context-sonnet-baseline
type: scouting
date: 2026-10-21
commit: 67a04cb
---

## What We're Doing

The operator wants to answer one simpler question before adding retrieval machinery: if Sonnet sees the whole propose-split context for a target, can it already produce better theory and rubric-edit drafts than the current sampled prompt? The goal is not to build a smarter retriever yet; it is to test whether retrieval is an accuracy improvement or merely a context-management optimization.

## Findings

- **F1** — operator, this conversation — the next experiment should be a **full-context Sonnet baseline**: feed the proposer the whole propose split for a target (roughly 70 usable pairs on `location`) and see whether it produces better theories and candidate edits before any Jev reranking layer is introduced.
- **F2** — `docs/features/rubric-recalibration/scouting.md` F6, F7, F9, F14, F15, F16 — the loop's core theory is still semantic, not n-gram, and the artifact is rubric text plus a small reviewable diff. Search-like machinery is rejected at current volume unless it clearly improves the output; "no edit proposed" is a valid result.
- **F3** — `docs/features/example-rerank/scouting.md` F1–F5 — the retrieval-layer idea was explicitly framed as a later spike to help the proposer get a tighter packet, but it was never established as an accuracy win. The docs already say the pair-shaped sketch was overengineered and that Jev should only be introduced if the simpler baseline does not suffice.
- **F4** — `scripts/recalibrate_rubric.py:252-299` — the current loop already builds a proposer prompt, runs a live model, and records candidate theories and train/held-out bucket counts. That means a full-context baseline can be tested by changing what goes into the proposer prompt, not by rewriting the rest of the loop.
- **F5** — `docs/features/rubric-recalibration/scouting.md` F13, F21 — the current target sizes make the baseline testable now: `location` is eligible and has enough usable pairs to give the proposer a large context slice, while still being small enough to fit a one-pass experiment.
- **F6** — operator, this conversation — the intended learning is comparative: if full-context Sonnet is already good enough, Jev reranking stays a later optimization; if it is materially worse, that justifies the added retrieval complexity.
