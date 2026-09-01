---
feature: review-ux
type: bearing
date: 2026-08-31
commit: efe0c2d
branch: main
status: implementing
parent: ../review-ux/scouting.md
scouting: ./sort-and-presentation-scouting.md
---

## Problem

The queue's sort/band and the JSON `/queue`'s sort/band never apply operator rulings —
`_queue_items` (web) and `get_queue` (api) both call `score_opening(assertions, config)`
with no `rulings`/`dimension_rulings`, while the per-opening rating page already does.
Rating something never changes its position in the queue. Terrain:
[sort-and-presentation-scouting.md](./sort-and-presentation-scouting.md) F1, F2.

## Done When

- [ ] Rating an assertion or dimension on an opening changes that opening's position in
      both `GET /` (HTML queue) and `GET /queue` (JSON) without a full page reload for the
      HTML case — test: seed two openings, submit a ruling that raises one opening's
      standing above the other's, assert the order flips in both responses (→ scouting F1)
- [ ] `_queue_items` and `get_queue` compute `standing`/`reach`/`band` from the same
      rulings the rating page uses for that opening — test: rate an opening via the rating
      route, then assert `GET /queue`'s entry for it matches `GET /openings/{id}/score`
      exactly (→ scouting F1)
- [ ] Existing queue/rating tests continue to pass unmodified where they don't depend on
      the old no-rulings queue behavior (→ scouting F1)

## Approach

- `_latest_ruling_by_assertion` and `_dimension_rulings_by_target`
  (`src/screen/web/routes.py:180-194`) are pure, I/O-free dedup logic — exactly what
  `api/scoring.py`'s docstring already claims ("glue between routes and the pure
  Scorer... no I/O of its own"). Promote them to public functions there
  (`latest_ruling_by_assertion`, `dimension_rulings_by_target`) so both call sites import
  one shared, public interface instead of `api/routes.py` reaching into `web`'s private
  helpers or duplicating them (→ operator, this session)
- Both queue builders (`_queue_items` in web, `get_queue` in api) fetch
  `assertion_rulings_for_opening`/`dimension_rulings_for_opening` per opening (existing
  repo functions), dedupe via the promoted functions, and pass the result into
  `score_opening` — same sequence `_rating_context` already uses, now shared rather than
  reimplemented (→ scouting F1)

## Not Doing

- Any change to band thresholds, display, or raw-number rendering — separate leaf (→
  scouting F4, F5)
- Any change to sparkline/visualization — separate leaf (→ scouting F8, F9)
- Caching or batching the extra per-opening ruling lookups for queue-render performance —
  not measured as a problem yet; premature (open space)

## Testing

Test-first by default. Exempt: nothing.

## Recalibrate When

- Fetching rulings for every opening on every queue render is measurably slow with a real
  corpus — stop, this needs a caching/batching approach instead of a straight port of the
  rating page's per-opening lookup.

## Agreed

- Ship this fix alone, not bundled with the band/display rework — a regression fix and a
  design change are different kinds of review (→ operator, this session)
