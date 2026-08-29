---
feature: dimension-digest
type: bearing
date: 2026-08-29
commit: 4ed61f7
branch: main
status: orienting
scouting: ./scouting.md
parent: ./bearing.md
---

## Problem

The rating view lists assertions flat and unordered (→ scouting F1). Group them by
dimension and show each group's cached digest (from `generation.md`) above its
assertions, expandable to the raw list. Terrain: [scouting.md](./scouting.md).

## Done When

- [ ] `/openings/{id}/rate` groups assertions by dimension instead of one flat list
      → `tests/test_web.py`
- [ ] Each dimension group shows its cached digest text above the assertions
      → `tests/test_web.py`, asserts digest string appears once per group
- [ ] Existing per-assertion rendering (target, fit chip, provenance chip, quote) is
      unchanged underneath each group → `tests/test_web.py`
- [ ] Groups render in `rubric.yaml`'s dimension order (weight-descending), not
      insertion/created_at order → test asserts group order
- [ ] A dimension with no assertions still renders its group with a "not yet examined"
      digest, not an empty/broken block → `tests/test_web.py`

## Approach

- Grouping happens in `src/screen/web/routes.py`'s `rate_opening` (or a small helper it
  calls), keyed by `Assertion.target`, ordered by `rubric.yaml`'s declared dimension order
  (→ scouting F1).
- Reads the cached digest via whatever read function `generation.md` exposes (e.g.
  `digest_for(opening_id, target)`); this view never generates a digest itself, and never
  calls the live BAML adapter directly (→ generation.md Approach).
- Digest text renders as plain prose above the assertion list per group — no numeric
  score, no Fit-colored chip on the digest itself (→ scouting F4).

## Not Doing

- No digest generation or caching logic — that's `generation.md`.
- No change to `queue.html` — this bearing is the per-opening rating view only.

## Testing

Test-first by default. Nothing exempt.

## Recalibrate When

- `generation.md` isn't done yet and this view has nothing to read — stop, don't stub a
  placeholder digest in the display layer.

## Agreed

- Digest is prose only, no chip/color/number treatment — keeps wall 4 (precision ranks,
  bands display) intact for this new display element too (→ scouting F4).
