---
feature: rubric-mission-trajectory-split
type: bearing
date: 2026-09-24
commit: 583562a
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

`mission` blends two questions — customer-extraction and AI-narrative-authenticity — and
`extractive_business` is the same customer-extraction question `mission` already asks,
split by confidence tier rather than subject matter (→ scouting F1, F2, F4). The operator's
actual segmentation is subject-matter: `mission` = "would I want to be part of this if it
succeeds," `trajectory` = "will it succeed" — and AI-authenticity belongs under the latter,
not the former (→ scouting F4, F5).

## Done When

- [ ] `rubric.yaml` has no `extractive_business` dimension; `mission`'s fit_anchors carry
      the full customer-extraction question at one confidence-agnostic band.
- [ ] `trajectory`'s fit_anchors include a hype-vs-defensible-strategy signal (business
      claims, including but not limited to AI framing, that read as narrative rather than
      substantiated strategy).
- [ ] `mission` weight stays 2; `trajectory` weight stays 2 — no reweighting.
- [ ] `src/screen/types.py`, `extract.baml`, `research.baml` have no `extractive_business`
      reference; `uv run python scripts/check.py` passes.
- [ ] `docs/architecture/decisions.md` carries a new R-entry recording the merge/drop,
      superseding whatever it touches (S12's dimension list, if anything states it as
      current).
- [ ] `data/live/screen.db` rows tagged `extractive_business` are silently dropped at read,
      not migrated — verified by the existing `_valid_target_or_warn` path
      (`src/screen/store/mappers.py:32`) needing no new code, only the `Target` Literal
      shrinking (→ scouting F16).

## Approach

- Remove the `extractive_business` block from `rubric.yaml` entirely; fold its
  confidence-agnostic extraction question into `mission`'s definition/fit_anchors as one
  unified axis, no confidence-tier split (→ scouting F4, F13).
- Add a hype-vs-defensible-strategy anchor to `trajectory` — AI-authenticity is one instance
  of it, not the whole signal; word it generally rather than AI-specific so it covers any
  narrative-over-substance strategy claim (→ scouting F14).
- Strip the AI-authenticity clause out of `mission`'s definition/anchors — it moves, it
  isn't duplicated (→ scouting F5, F14).
- Remove `extractive_business` from `src/screen/types.py` (`_SCORING_TARGETS`, `Target`
  Literal) and from the BAML rubric-summary strings/tests, mirroring `drop-peer.md`'s steps
  (→ scouting F17, F18).
- Update the five tests that assert/fixture `extractive_business` as live (→ scouting F19),
  and the `rubric.yaml:25` no-special-treatment comment (→ scouting F20).
- D19's "no signal is the outcome of looking, not the default" shape (→ scouting F7) carries
  into `mission`'s merged anchors — Strong still requires having looked and found no
  extraction, not silence-by-default.

## Not Doing

- Not reweighting `mission` or `trajectory` for absorbing the merged/added signal — weight 2
  each, unchanged (→ scouting F15).
- Not addressing the case where `mission` scores poorly but the opening still ranks high in
  practice — deferred as a future problem, per operator (→ scouting F15).
- Not touching `agentic` — AI-authenticity is a strategy-honesty question for `trajectory`,
  distinct from `agentic`'s tooling-quality question (→ scouting F14).
- Not fixing `domain-model.md:44`'s pre-existing stale dimension list beyond what this
  change itself requires — that drift predates this bearing (→ scouting F11).

## Testing

Test-first by default. Exempt:
- `rubric.yaml`, `decisions.md` — prose/config.
- `extract.baml`, `research.baml` prompt strings — generated/prompt text, not logic.

## Recalibrate When

- If `check.py` or any test asserts a fixed dimension count/name list beyond the five named
  in scouting F19, update the assertion instead of routing around it.
- If merging AI-authenticity into `trajectory` makes its Poor/Mixed/Strong anchors span two
  unrelated failure modes awkwardly (health vs. narrative-honesty), stop and flag — that's a
  dimension-design question, not a wording tweak.

## Agreed

- Drop `extractive_business` entirely, `mission` absorbs the extraction question at one
  band — operator, same pattern as `stretch`'s drop-and-rename in `redefine-stretch.md`
  (→ scouting F13).
- AI-authenticity moves to `trajectory` as a hype-vs-defensible-strategy signal, not its own
  callout — operator (→ scouting F14).
- `mission` weight stays 2 — operator; a poor-mission/high-rank divergence is a future
  problem, not solved here (→ scouting F15).
