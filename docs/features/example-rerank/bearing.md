---
feature: example-rerank
type: bearing
date: 2026-10-21
commit: 67a04cb
branch: main
status: orienting
scouting: ./scouting.md
---

## Problem

The recalibration loop needs a thinner retrieval step so the proposer can ask for exactly the kind of examples it wants, then draft exact rubric language against a small returned packet. The operator wants that state to stay simple: an intent and a list of yes/no questions, with Jev ranking candidate examples in parallel and code doing the categorization. Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] A spike can take an intent plus a list of question strings and rank a small candidate example set into labeled categories (`strong-match`, `boundary`, `counterexample`, `too-weak`) → run it on a hand-built `location` fixture and print the categories
- [ ] The retrieval state passed through BAML contains intent and question strings only; no pair-shaped schema is needed to reach Jev → inspect the BAML state shape for the spike
- [ ] Jev judgments are parallel over the questions for a single example, and code — not Jev — performs the final category assignment → a fake classifier can drive the spike deterministically
- [ ] The returned packet is balanced rather than a raw top-k list — it includes examples to draft toward and examples to draft against → compare packet composition on a hand-built fixture

## Approach

- Keep the retrieval contract to intent + a list of plain-language questions, not a pair-shaped payload or a second schema layer (→ scouting F1, F2)
- Use Jev as a reranker over those questions, one coherent judgment per question, and keep aggregation in code (→ scouting F2)
- Return a small, balanced packet of examples — positives, boundary cases, and counterexamples — rather than a simple sorted list (→ scouting F4)
- Spike first on a hand-built `location` set so the category boundaries are legible before this touches the main loop (→ scouting F3, F5)

## Not Doing

- A pair-based BAML retrieval schema — the operator wants that simplification removed (→ scouting F1)
- Asking Jev to summarize, reason aloud, or do arithmetic; it only judges the stated questions (→ scouting F2)
- Integrating this into the main recalibration loop before the spike proves the categories are useful (→ scouting F5)

## Testing

Test-first by default. Exempt:
- none

## Recalibrate When

- Jev cannot reliably separate clear positives from boundaries on the spike — the question wording is wrong or the example set is too noisy
- The example packet needs more structure than a list of questions can reasonably express — then this becomes a richer schema, but not before the spike proves it
- The balanced packet still leaves the proposer drafting vague theories instead of exact anchor language — the retrieval layer is not yet sharp enough

## Agreed

- The retrieval state should survive only as intent plus simple questions, not a pair-shaped context object — the pair was overengineered (→ scouting F1)
- Jev is for ranking judgments, not final selection or freeform drafting — code keeps the math and the packet assembly (→ scouting F2)
- The goal of retrieval is a small packet the proposer can draft exact language against, not a broad prompt with more prose (→ scouting F4)
