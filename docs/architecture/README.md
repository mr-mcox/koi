---
name: architecture-index
type: index
date: 2026-08-26
---
# Architecture

Screening pipeline: a job posting URL becomes typed Assertions about a Company and an
Opening, which a Scorer later turns into a ranked queue. Judgment is agentic; dispatch is
deterministic. Flat files, no database, backend only.

**Read this before scouting any feature.** It classifies the ground. The documents it
points at hold the detail — this file never restates them, so that adding to them doesn't
strand a summary here.

## Girders — changing one is an escalation

- **The walls** → [domain-model.md](domain-model.md) · partly enforced in `tests/test_types.py`
- **Fit and provenance are separate axes, always** → [decisions.md](decisions.md) E2, S8 ·
  `tests/test_types.py`
- **Companies and Openings are separate entities** → [decisions.md](decisions.md) E4
- **Research is multi-pass and append-only, under an explicit contract** →
  [decisions.md](decisions.md) E5
- **Rubric text is load-bearing and versioned** — the extraction prompt is generated from
  `rubric.yaml`, never freeform → [decisions.md](decisions.md) R4 · `tests/test_rubric.py`
- **The dispatcher owns every tool call and all state mutation.** `DecidePlan` is the only
  LLM-shaped decision; Tavily is dispatched, never agent-called. Rejecting this means
  rejecting the four-state loop → `tests/test_dispatcher.py`
- **No agent framework.** BAML covers structured output; adding a framework is a vocabulary
  change, not a dependency change
- **`intake/` never imports `loop/`** — dependency direction runs one way · *unenforced*
- **Private config stays private** — no real company name, salary, résumé content, or
  collected evidence in a committed file → [domain-model.md](domain-model.md) · `scripts/check.py`
- **Discipline gates** → [discipline.md](discipline.md) · `scripts/check.py`

## Volatile — expected to move. Don't stabilize, don't abstract, don't build on it.

The architecture's job is to keep each of these cheap to change later.

- **Named volatility areas** → [domain-model.md](domain-model.md)
- **Open questions**, each stating what would settle it → [open-questions.md](open-questions.md)
- **Anything tagged `provisional`** → [decisions.md](decisions.md)
- **LLM provider and model** — operator config, not a code dependency

## Everything else is open space. Decide it, note it, move on.

## Contents

- [domain-model.md](domain-model.md) — entities, boundaries, invariants, volatility areas
- [decisions.md](decisions.md) — durable decisions, tagged `demonstrated` / `adopted` / `provisional`
- [open-questions.md](open-questions.md) — what's deliberately undecided
- [discipline.md](discipline.md) — the objective checks the codebase must keep passing
- [learnings.md](learnings.md) — prototype observations that shaped the above
- [prototype-decisions.md](prototype-decisions.md) — superseded prototype-era record
