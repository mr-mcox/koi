---
feature: research-target-opportunity
type: bearing
date: 2026-11-03
commit: aa6b3ab
branch: main
status: decomposed
scouting: ./scouting.md
---

## Problem

Target choice is a deterministic ranker handing `DecidePlan` an opaque slug, so research never aims at what's actually worth learning, and it can't use the fuzzy signals a person would (what was searched, what came of it, which dimensions tend to come up dry). We want a model to choose, once per research opportunity, a question bound to one dimension, and the mechanics to hold the planner to it. Terrain: [scouting.md](./scouting.md)

## Done When

- [x] Each research opportunity (intake pass or batch block) makes exactly one question-step call before the first `DecidePlan`, and every `DecidePlan` in that pass receives the same question and dimension → `tests/research/test_dispatcher.py`
- [ ] The question step's input carries the rubric ✓; for each dimension, past queries paired with the assertion text their fetches produced ✓; pool-wide and this-opening run yield ✓; and the dimension's current `half_width` → request-shape test on the step's input builder
  - [x] rubric ✓
  - [x] past queries + assertion text ✓ (`render_assertion_history`)
  - [x] yield aggregation ✓ (`fold_target_yield`)
  - [x] yield_summary rendering and half_width per dimension ✓
- [x] Yield aggregation counts only slugs in the current `Target` vocabulary and is computed from existing `decide_plan` events with no new trace field → `tests/research_trace/` test over `trace_shapes.json` plus a retired-slug line
- [x] A dimension the step names outside the `Target` vocabulary fails the pass loudly; it is not silently remapped → dispatcher test
- [x] `rank_targets`, `select_primary_target` and `active_target_action_cap` are gone; one per-pass budget remains → `grep -rn` shows no hits in `src/`
- [x] Every shape in `trace_shapes.json` still loads and replays to the same `target_stalls`; new traces carry the question as an optional field → `tests/research_trace/test_events.py`
- [x] decisions.md records the girder change, and README's girder line names two LLM-shaped decisions → E9 applied
- [x] `uv run python scripts/check.py` passes

## Approach

- A new BAML function, called by the dispatcher, returns `{dimension, question}`. It performs no tool calls and mutates no state; the dispatcher owns when it runs and what changes. The girder extends, it doesn't break (→ scouting F11, F19)
- The question step is the only target chooser; the deterministic ranker is deleted, not kept as a pre-filter or fallback, and a failed call fails the pass like `DecidePlan` does (→ scouting F16, F29, F31)
- The chosen dimension is written into the existing `primary_target`, so stall replay keys on it unchanged for old and new traces; the question text is a new optional audit field (→ scouting F13, F30, decisions E8)
- Yield is derived, not stored: pool-wide and per-opening runs/yielded per dimension are folded from `decide_plan` events at the start of each opportunity (→ scouting F23, F32)
- Query→assertion pairing joins each assertion's citation URL to the search whose hits contained it, and drops the pairing when no search contains the URL (→ scouting F25, F34)
- **Fixed leash, no yield-based extension:** one budget, `research_block_turns`, per opportunity. The live data shows a run that has already yielded is no more likely to yield again (→ scouting F21, F33)

## Not Doing

- Outbound-link backlog — its own feature (→ `docs/features/outbound-link-backlog/scouting.md`)
- Extending the leash on yield — unsupported by F33; revisit via Recalibrate
- A dry-streak early exit inside a pass — a k=3 cutoff would have cut 15 late yields (F35); cross-pass "nothing to see here" comes from the yield signal the step reads
- Questions spanning several dimensions, or stall accounting keyed on question text
- Caching yield aggregates, or a fallback when the question step fails

## Testing

Test-first by default. Exempt:
- `src/screen/baml_client/` — generated
- `src/screen/baml_src/research.baml` prompt text — covered by `baml-cli test` smoke tests, run by hand (cost per run), not in `check.py`

## Recalibrate When

- If the question step names the same low-yield dimension pass after pass on one opening, stop: the yield signal isn't steering it.
- If question-driven traces show post-yield steps producing well above the F33 baseline (~10%), stop: the extension case is back on.
- If the question step's input passes ~8k tokens on a well-researched opening, stop: the pairing needs summarizing (digest, F27), and that's a shape change.
- If the citation-URL join attributes fewer than ~80% of assertions to a query, stop: F26's rendering needs rethinking.
- If keeping old traces replaying needs more than the optional question field, stop (decisions E8 escalation).

## Agreed

- Two LLM-shaped decisions in the research loop, not one; the dispatcher still owns every tool call and every mutation (→ scouting F19)
- One dimension per question; other-dimension assertions are an accepted side effect, not multi-target questions (→ scouting F14)
- Retire the deterministic ranker rather than keep it as a filter or fallback (→ scouting F16)
- Pick once per opportunity; the next draw picks a new opening and a new question, with no mid-pass re-targeting (→ scouting F20)
- Turn budget and per-target cap collapse into one number (→ scouting F12, F22)
- The link backlog is a separate follow-up feature (→ scouting F17)
