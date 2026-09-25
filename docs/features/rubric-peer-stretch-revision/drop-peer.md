---
feature: rubric-peer-stretch-revision
type: bearing
date: 2026-09-24
commit: 531ee63
branch: main
status: done
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

`peer` currently scores public evidence (named senior hires, engineering-blog depth, hiring-bar
detail) at weight 2. The operator says this isn't the real signal: evaluating who they'd work
with requires interview/conversation history, which the research pass cannot do (→ scouting
F1-F3).

## Done When

- [x] `rubric.yaml` has no `peer` dimension and no references to peer-specific concepts.
- [x] `src/screen/types.py` `_SCORING_TARGETS` and `Target` Literal no longer list `peer`.
- [x] BAML `Assertion` schema (extract.baml) target enum no longer lists `peer`.
- [x] `uv run python scripts/check.py` passes; grep for `peer` in `rubric.yaml`,
      `src/screen/types.py`, and `src/screen/baml_src/extract.baml` returns nothing
      (modulo prose comments).
- [x] `docs/architecture/decisions.md` carries a new R-entry: drop `peer`, superseding R5,
      noting the public-evidence signal (named hires, blog depth, etc.) is discarded, not
      folded elsewhere, because the operator can't act on it during screening.

## Approach

- Remove the dimension block from `rubric.yaml`; leave surrounding commentary intact.
- Update `src/screen/types.py` closed vocabulary — remove from both `_SCORING_TARGETS` and
  `Target` Literal. If other code references `peer` as a literal, it will surface via `check.py`
  or tests; fix inline as a same-bearing edit.
- Regenerate or hand-edit the BAML `Assertion` target enum to remove `peer`.
- Note in `decisions.md`: this reopens OQ16's "software core to strategy" half, previously
  folded into `peer`; no new dimension is created here, so that signal is unhomed again.

## Not Doing

- Not preserving `peer` as a manual/operator-only dimension or post-interview-only field.
- Not moving its Strong signals (named senior hire, blog depth, hiring-bar detail) into
  `schematic`, `trajectory`, or a new dimension.

## Testing

Test-first by default. Exempt:
- `rubric.yaml`, `decisions.md` — prose/config.

## Recalibrate When

- If `check.py` or any test asserts the list of scoring dimensions has a fixed count/names,
  update the assertion instead of routing around it.

## Agreed

- Drop `peer` outright, no replacement — operator: "it's not useful for screening"
  (→ scouting F3).
- Discard R5's measured public-evidence calibration (10/10 boilerplate → Mixed, Strong cases
  categorically distinct) rather than fold it elsewhere — operator's framing is that this
  signal is not actionable for screening (→ scouting F2).
