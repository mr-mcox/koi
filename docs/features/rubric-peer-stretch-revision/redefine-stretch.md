---
feature: rubric-peer-stretch-revision
type: bearing
date: 2026-09-24
commit: 531ee63
branch: main
status: orienting
parent: ./bearing.md
scouting: ./scouting.md
---

## Problem

`stretch` currently scores ability-distance from the operator's level (inverted-U, seniority as
strongest signal). The operator's live corpus shows this doesn't discriminate: 89 Strong / 3
Mixed / 0 Poor, nearly all title/seniority matches across wildly different domains (→ scouting
F9). The operator actually uses the concept as a discipline-preference axis: LLM-based solution
design + standard ML/deep learning = Strong; data/analytics-eng/devops/backend = Mixed;
frontend/embedded = Poor (→ scouting F8).

## Done When

- [ ] `rubric.yaml` replaces the `stretch` dimension with a renamed slug whose definition,
      `fit_anchors`, `look_for`, and `notes` encode the operator's three-tier discipline ladder.
- [ ] `src/screen/types.py` `_SCORING_TARGETS` and `Target` Literal use the new slug instead of
      `stretch`.
- [ ] BAML `Assertion` schema target enum uses the new slug instead of `stretch`.
- [ ] `uv run python scripts/check.py` passes; no `stretch` reference remains in
      `rubric.yaml`, `src/screen/types.py`, or `src/screen/baml_src/extract.baml` as a scoring
      dimension.
- [ ] `docs/architecture/decisions.md` carries a new R-entry: rename/redefine the dimension,
      superseding R1, because ability-distance isn't the signal in this corpus.

## Approach

- Pick a new slug (e.g. `craft_direction`) at implementation time; rename forces re-fetch so
  old `Strong` assertions under the old semantics don't silently adopt the new meaning.
- Write `fit_anchors` from the operator's three tiers verbatim: Strong = genuine mixture of
  LLM-based solution design (AI engineering) + standard ML/deep learning; Mixed = data
  engineering, analytics engineering, devops, backend engineering; Poor = frontend
  engineering, embedded systems and other areas without existing depth to draw from.
- Write `look_for` in two tiers: JD-legible baseline (title/responsibilities describe the
  discipline mix) plus corroboration signal (engineering blog, conference talks, discussion of
  shipped ML/AI work). Explicitly flag the inverse: aspirational "do AI/ML" language with no
  corroborating evidence is a red flag for immature data/infrastructure setup.
- Remove the old inverted-U, ability-distance language, the résumé-alignment references, and the
  "least trustworthy / expect overrides" `notes` caveat — the corpus finding undermined that
  caveat's premise.
- Keep weight 3 unless operator overrules — no new information argues otherwise.

## Not Doing

- Not excluding the new dimension from research gap-detection like `domain` (OQ12) — it is
  JD-legible by default, but corroboration (or its absence) is researchable and changes
  confidence (→ scouting F17).
- Not rewriting `agentic` anchors — the operator's clarifying examples matched existing text
  closely (→ scouting F10).
- Not touching `schematic` — shape-of-work stays independent (→ scouting F8).

## Testing

Test-first by default. Exempt:
- `rubric.yaml`, `decisions.md` — prose/config.

## Recalibrate When

- If the operator, on reading the drafted `fit_anchors`, wants override-likelihood to become
  an actual scorer input (F14), stop — that's a design escalation, not a wording tweak.
- If BAML codegen requires more than a simple slug edit to support the rename, flag whether
  this is the second OQ13 instance.

## Agreed
- Redefine `stretch` as a discipline-preference ladder, discarding ability-distance/inverted-U
  (→ Approach, scouting F8, F9).
- Rename the slug; backfill/re-fetch from JDs where possible (→ Approach, scouting F16).
- Keep in normal research gap-detection, unlike `domain` (→ Not Doing, scouting F17).
- Leave `agentic` untouched (→ Not Doing, scouting F10).
