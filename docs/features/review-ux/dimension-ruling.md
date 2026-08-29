---
feature: review-ux
type: bearing
date: 2026-08-30
commit: dafddc0
branch: main
status: implementing
parent: ./scouting.md
scouting: ./dimension-ruling-scouting.md
---

## Problem

`docs/CURRENT.md` names `DimensionRuling` as the next tip: an operator's own placement of
"where does this dimension land, given everything" (domain-model.md §Ruling), distinct
from `AssertionRuling`'s per-claim confirm/override. F31 (parent scouting) deferred this
until an assertion-level corpus existed; F34 confirms it now does (52 assertions, 10
rulings, 5 openings). Terrain: [dimension-ruling-scouting.md](./dimension-ruling-scouting.md).

## Done When

- [ ] `DimensionRuling` type and table exist: `opening_id`, `target`, continuous `fit`
      (mean, `[-1,1]`), continuous `settledness` (`[0,1]`, 0 = loose opinion, 1 =
      strongest stated conviction), `created_at` — sibling to `AssertionRuling`, not a
      shared type (→ scouting F41, review-ux/scouting F25/F28)
- [ ] The rating page shows, per dimension group, a **compact single-click control** to
      submit a `(fit, settledness)` pin and displays any existing pin distinctly from the
      digest and the assertion list beneath it (→ scouting F39)
- [ ] The dimension-ruling control sits in a compact row with the digest text
      right-justified against it, and the assertion controls (provenance glyph + fit
      buttons) sit on one line (layout regression from the unstyled form)
- [ ] Submitting a pin writes/updates the `DimensionRuling` for that `(opening_id,
      target)` — HTMX partial swap, no full reload (→ review-ux/scouting F20)
- [ ] `score()` accepts an optional dimension-ruling override; when present for a target,
      it substitutes the whole computed `_TargetStats(mean, half_width)` for that target,
      superseding any per-assertion rulings underneath — test: pinning a dimension changes
      its target's contribution to `standing` independent of the assertions filed against
      it (→ scouting F35, F36, F37)
- [ ] Existing JSON scoring routes and assertion-ruling behavior are unchanged and still
      pass their tests

## Approach

- Sibling type + table + upsert-by-`(opening_id, target)`, following the
  `AssertionRuling`/`assertion_rulings` shape exactly (migration, mappers, repo) — the
  established pattern for a new ruling kind here (→ scouting F41)
- Scorer override is a second, independently-optional parameter to `score()` — a
  target-keyed `dict[str, DimensionRuling]` or equivalent — not a variant of the
  existing assertion-keyed `rulings` param, because it replaces the aggregate
  `_TargetStats`, not one assertion's fit inside the sum (→ scouting F35, F36)
- One substitution point serves both scoring dimensions and constraints — both already
  reduce to the same `_TargetStats` shape before diverging into affine-mapping
  (→ scouting F37)
- Continuous input is a **single 2D click-pad**: one click sets both fit (x-axis,
  `[-1, 1]`) and settledness/conviction (y-axis, `[0, 1]`) and submits via HTMX. A small
  delegated client-side handler updates hidden form inputs and triggers the form submit;
  this reverses the earlier no-JS-slider choice (F40) after the operator found two
  independent sliders too click-heavy. The POST contract (`mean`, `settledness` form fields)
  stays unchanged so the existing server route and tests still hold.
- Clamp `mean` to `[-1,1]` and `settledness` to `[0,1]` at the type/validation
  boundary; `half_width` is *derived* from `settledness` via a configured
  `hw_max`/`hw_min` in `scoring.yaml` (`half_width = hw_max - settledness * (hw_max -
  hw_min)`, `hw_min > 0`) — rising conviction narrows the distribution but never to a
  point estimate, matching the range the Scorer's sampling code already assumes
  elsewhere (→ scouting F38, F43, F45)
- Pins are not revertable: no unset/delete control; resubmission upserts the same
  `(opening_id, target)` row, mirroring `AssertionRuling`'s re-rating pattern
  (→ scouting F46)

## Not Doing

- Rating-VOI / triage — this bearing is the last precondition, not the triage mechanism
  itself (→ docs/CURRENT.md framing, review-ux/scouting F3)
- Queue applying rulings — a separate, previously-named gap not reopened here unless the
  operator raises it again (→ dimension-ruling-scouting "Not Yet Settled")
- Any interaction with `DimensionDigest` caching/invalidation — confirmed unnecessary,
  not a design gap (→ scouting F44)
- Snap-to-bucket or discretization of the continuous pin — already ruled out
  (→ review-ux/scouting F27, scouting F42)

## Testing

Test-first by default. Exempt:
- `src/screen/web/templates/rating.html` — Jinja template, no unit-testable logic of its
  own; covered by route integration tests (same exemption as prior review-ux leaves)

## Recalibrate When

- The Scorer substitution can't cleanly ignore per-assertion rulings underneath a pinned
  target — stop, the precedence rule in Done When is wrong
- `settledness`-to-`half_width` derivation produces visibly wrong sampling behavior at
  the bounds — stop, `hw_max`/`hw_min` need rework

## Agreed

- The settledness slider reads as stated conviction, not spread directly — 0 is a loose
  opinion, 1 is maximum conviction with some spread still intact; `half_width` is
  derived from it via configured bounds, never reaching zero (→ scouting F43, operator)
- `hw_max`/`hw_min` are named values in `scoring.yaml`, not literals in code
  (→ scouting F45, AGENTS.md "measure before model")
- Pins are not revertable — no unset control; resubmission still replaces the value
  (→ scouting F46, operator)
