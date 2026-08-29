---
feature: assertion-rating-layout
type: bearing
date: 2026-08-29
commit: ac3bdb1dfde5ea8db6192904764db25247a869bd
branch: (detached, worktree bold-fig)
status: done
parent: ../review-ux/scouting.md
scouting: ../review-ux/scouting.md
---

## Problem

review-ux (→ `../review-ux/scouting.md`) needs the rating surface to be honest and
inspectable before the operator can override anything. The current rating template lists
assertions without surfacing their source citations and without distinguishing a model
proposal from an operator ruling (F33). This slice fixes the display; the submit capability
is a separate follow-up leaf.

## Done When

- [x] `AssertionRuling` type and table exist, read-only query in place: `assertion_id`, `fit: Fit`,
      created timestamp. Sibling to future `DimensionRuling`, not a scoped union (→ scouting F25, F28)
- [x] The rating page renders one distinct row/card per assertion, showing its `target`, the
      LLM's proposed `fit`/`provenance`, the `chunk`, and a clickable citation link from
      `assertion.citations[].url` (→ scouting F33)
- [x] Each row shows any existing operator `AssertionRuling` distinctly from the LLM proposal
      (e.g., separate chips or labels) — empty state handled gracefully (→ scouting F33)
- [x] No submission controls or forms yet; the page is read-only for rulings (→ scouting F33, F31)
- [x] Existing JSON and HTML routes still pass their tests after the change

## Approach

- Define `AssertionRuling` type and table here (read-only use), so the submit leaf can later
  write into the same table without a schema change (→ scouting F25, F28)
- Read any existing `AssertionRuling` records for the opening alongside the assertions; pass
  both into the template so the UI can pair them by `assertion_id` (→ scouting F33)
- Render citations as direct links to `url`; host/domain can be shown as link text (→
  scouting F33)
- Visual distinction between model proposal and operator ruling is a CSS class pair, not new
  data — `fit-*`/`provenance-*` already exist; add an `author-*` or `ruling-*` vocabulary (→
  scouting F24, F33)
- Server-rendered Jinja2, HTMX-ready markup but no HTMX behavior yet — the structure should
  accept `hx-*` attributes later without redesign (→ scouting F22)
- No writes or score changes; this slice is a route/template read of existing data only

## Not Doing

- Submit/override controls for assertions — the next leaf (`assertion-ruling-submit`) (→
  scouting F33)
- Scorer override or queue re-sort — no writes, no score changes (→ scouting F31)
- `DimensionRuling` / continuous placement — still exploratory, deferred (→ scouting F25-F30)
- Rich citation previews, quote expansion, or multiple-citation accordion — link to source is
  enough for now
- Grouping assertions by dimension — not needed for the row layout; keep a flat list

## Testing

Test-first by default. Exempt:
- `src/screen/web/templates/rating.html` — Jinja template has no unit-testable logic of its
  own; behavior covered by route integration tests

## Recalibrate When

- The layout design requires a domain change (e.g., a new field on `Assertion` or `Citation`)
  — stop, that belongs upstream
- Submit capability is needed before the layout can ship — this would mean the split was
  wrong and the two leaves should be merged
- A richer citation display becomes a requirement rather than a nicety — that is a new leaf

## Agreed

- Layout-first, submit-second split of the assertion-ruling steel thread (→ scouting F33)
- Citation links point to the recorded `url`, no separate fetch/preview step (→ scouting F33)
- Model proposal and operator ruling are visually distinct, not merged into one chip (→
  scouting F33)
