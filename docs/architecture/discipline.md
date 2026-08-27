---
name: discipline-gates
type: reference
date: 2026-08-25
provenance: extracted from the steel-thread parent brief during compaction
companions: decisions.md, domain-model.md
---
# Discipline Gates

Project-wide code discipline. Lives here rather than in a feature brief because it outlives
any one feature — briefs are deleted at compaction, this isn't.

Coverage *ratchets* (the logseq-navigator pattern) were considered and rejected in favour of
**gates**: binary pass/fail per file, not a gradient that drifts upward by accident.

## The three axes

**1. Coverage is binary.** Per-file coverage must be at or above the current tier. Below is a
hard failure. A file may be **exempt**, but exemption requires an inline reason at the exempt
entry, and the exempt count is bounded by a budget. The point is not "every line is tested" —
it is "every file commits to being either tested or a documented seam."

**2. Type-punt count.** `# type: ignore`, `# pyright: ignore`, and `# noqa` across `src/screen/`
are bounded. Goal: type punts surface as architecture pressure — a Protocol, a decomposition —
rather than a growing pragma count.

**3. Complexity ceilings.** Cyclomatic complexity per function ≤ 7, function ≤ 50 lines, file
≤ 200 lines. Catches long-function sprawl, the LLM author's most common laziness shape.

## Where the numbers live

**Tier values live in `tests/test_discipline.py`**, inline beside the assertions that read them.
That file is the single source of truth. Nothing else — no brief, no bearing, no slice — restates
a tier value; a document that does immediately drifts.

Tiers move **upward** when the architecture earns it, downward never. Any change in either
direction is a `decisions.md` entry, including a *reduced* exempt budget ("we decomposed this
out, exempt count went down").

## Division of labour

`ruff` owns non-topline imports (`PLC0415`), complexity (`C901`, max 7), function length
(`PLR0915`, max 50), unused imports (`F401`), raise-from chains (`B904`). `black` owns
formatting. Config in `[tool.ruff]` / `[tool.black]`.

`tests/test_discipline.py` keeps only what a linter structurally cannot: per-file coverage
tier and exempt-file budget. Those are project-state values that change with the architecture,
not code-shape rules.
