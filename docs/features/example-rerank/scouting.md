---
feature: example-rerank
type: scouting
date: 2026-10-21
commit: 67a04cb
---

## What We're Doing

The operator wants the next step to be a lightweight retrieval layer: the proposer states an intent and a small set of yes/no questions, Jev scores candidate examples against those questions, and code returns a tight packet the proposer can draft exact language against. The BAML state should stay simple — intent plus question strings, not a pair-shaped schema.

## Findings

- **F1** — operator, this conversation — the retrieval step should not be pair-shaped in BAML. The useful state is the proposer’s intent plus a list of simple questions/criteria. The pair was an overfit from the earlier sketch; the operator wants to remove it before implementation.
- **F2** — `/Users/mcox/dev/pi-platform/.pi/skills/jev/SKILL.md` — Jev is a classifier, not a chat model; it takes typed state/questions, answers one coherent judgment per question, batches questions about the same state, and should not be asked to do arithmetic or freeform generation. This makes yes/no statements the right primitive and keeps aggregation in code.
- **F3** — `scripts/recalibrate_rubric.py:100-173, 252-299` — the current loop already has a proposer that emits theories and a reranker/evaluator that judges examples; the missing piece is a thinner retrieval layer that chooses which examples to show the proposer before it drafts text.
- **F4** — operator, this conversation — the desired output of the retrieval layer is a balanced packet of examples the proposer can write exact anchor language against, not another broad prompt with more prose.
- **F5** — current loop behavior, `scripts/recalibrate_rubric.py:252-299` — today the CLI measures baseline and candidate quality after the proposer already has its context; a retrieval spike would sit earlier and should be validated on a tiny hand-built set before it is wired into the loop.
