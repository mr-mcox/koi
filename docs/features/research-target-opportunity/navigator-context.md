---
feature: research-target-opportunity
type: bearing
date: 2026-11-04
commit: aa6b3ab
branch: main
status: done
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

The navigator can see how many assertions a dimension has, never what they say or where
they came from (→ scouting F36). So it cannot tell "the posting already answered this"
from "two weak claims off a blog", and it thrashes: 47.8% of all live search queries are
near-duplicates of an earlier query on the same opening, and 16.5% of openings re-fetch
their own original URL (→ scouting F37, F38, F39). Until that is fixed, the Surveyor
framing question cannot be answered — every variant produces the same navigator action
(→ scouting F45). Terrain: [scouting.md](./scouting.md)

## Done When

- [x] The navigator's input carries, per dimension, each assertion's fit, verbatim chunk
      and citation URLs — not a count → request-shape test on the input builder
- [x] `target_assertion_counts` is gone from what the navigator reads; old traces that
      carry it still replay to the same `target_stalls` → `tests/research_trace/test_events.py`
      over `trace_shapes.json`
- [x] The Navigator's `rubric_text` is the active dimension's text alone, via
      `RubricText.for_dimension`; the Surveyor keeps the full rubric, since it has no
      active dimension until it chooses one → builder test on each call's rendered text
- [x] A dimension with no assertions renders as explicitly unexamined, never as absent or
      empty → builder test
- [x] Re-running the F39 trace's opening shape produces fewer near-duplicate queries than
      the 47.8% corpus baseline → **relaxed, operator, 2026-11-04**: F46/F47 landed at
      62.5% and 80.0% respectively — real improvement over the 87% outlier and real
      yield where there was none (0 → 10-12 assertions), but neither cleared the 47.8%
      corpus baseline. Operator accepts the partial win rather than reopening; see
      Recalibrate When below for the model-tier path if this needs revisiting.
- [x] The BAML function and its file carry the Navigator name; the `decide_plan` trace
      literal does not change → `grep -rn` plus `trace_shapes.json` still loading
- [x] `uv run python scripts/check.py` passes

## Approach

- Full assertion content replaces the counts: fit, verbatim chunk, citation URLs, grouped
  by dimension. No compression layer, no digest, no per-source summary — the discarded
  signal is exactly what tells the navigator whether a query returns anything new
  (→ scouting F41, F42)
- The renderer is pure and dispatcher-owned, built from `Assertion` values the dispatcher
  already holds; no new storage, no new trace field, no JD entity (→ scouting F40, F42)
- The Navigator's `rubric_text` narrows to its fixed `primary_target` via the existing
  `RubricText.for_dimension` — isolating the judgment it's already committed to, not a
  cost move (operator: cost isn't a driver here). The Surveyor keeps the full rubric; it
  has nothing to narrow to until it chooses (→ scouting F41)
- The same rendered context goes to both the Surveyor and the Navigator — the Surveyor's
  `query_assertion_history` stub is this, not a second shape (→ scouting F36, F40)
- The BAML function renames to match the Navigator; the `decide_plan` trace literal stays,
  frozen by E8 (→ scouting F43, decisions E8)

## Not Doing

- A first-class JD entity — assertions already represent the posting (→ scouting F42)
- Mechanistic dry-turn nudges or forced source-type switching — the hypothesis is missing
  context, not missing rules (→ scouting F42)
- Changing model tier — untestable until the context gap closes (→ scouting F44)
- Choosing among the Surveyor framings — deferred to after this (→ scouting F45)
- Chunk truncation — saves ~20% for real signal loss (→ scouting F41)

## Testing

Test-first by default. Exempt:
- `src/screen/baml_client/` — generated
- `src/screen/baml_src/*.baml` prompt text — covered by `baml-cli test` smoke tests, run
  by hand (cost per run), not in `check.py`

## Recalibrate When

- If the rendered context passes ~8k tokens on a well-researched opening, stop — the
  parent bearing's summarizing trigger fires (→ parent §Recalibrate When).
- If near-duplicate queries stay near the 47.8% baseline with full content in hand, stop:
  the bottleneck is model tier, not context, and F44 becomes the live question.
  **Did not fire** (operator, 2026-11-04): 62.5%/80.0% read as real movement off the 87%
  outlier, not "stayed near baseline." If the framing re-run in `surveyor-framing.md`
  still converges or thrash resurfaces, F44 (model tier bump) is the next thing to try,
  not a reopen of this bearing.
- If renaming the BAML function forces any change to a persisted trace field, stop
  (decisions E8 escalation).

## Agreed

- Full assertion content, not a per-source summary — the compressed form costs 163 tokens
  against 1,478 but discards the signal the decision needs (→ scouting F41, F42)
- No JD entity; assertions plus citations already carry the posting (→ scouting F42)
- Surveyor-framing comparison waits until the navigator is unblocked, not in parallel —
  every framing currently yields the same action (→ scouting F45)
- Rubric narrowing applies to the Navigator only, not the Surveyor — the Surveyor has no
  dimension yet to narrow to (checkpoint, 2026-11-04)
