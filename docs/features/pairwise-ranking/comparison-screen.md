---
feature: pairwise-ranking
type: bearing
date: 2026-09-17
commit: c17db8e
branch: rank-pool
status: completed
parent: ./bearing.md
scouting: ./comparison-screen-scouting.md
---

## Problem

compare.md's backend (storage, batch fit, auto-tie) is done, but nothing calls it:
`pool_for_screening`'s comparison args go unused in production (scouting F2), and no route
lets the operator submit a comparison. This node is the minimal tracer: manually pick two
openings and a dimension, declare a winner or tie, confirm the live ranking moves.
Picking the pair/dimension for the operator (`select_comparison`) is later work (→
scouting F15). Terrain: [comparison-screen-scouting.md](./comparison-screen-scouting.md).

## Done When

- [x] `/queue`'s live pool score reflects a comparison-derived covariance once one is
      submitted — the answer to scouting F2 → integration test through the web route,
      asserting a submitted comparison changes rank order
- [x] The operator can pick any two openings and a dimension and submit A/B/tie from a
      page reachable off the queue — manual selection, no suggestion picker (→ scouting
      F15) → `tests/test_web.py`
- [x] Submitting a comparison appends a row via `append_comparison`, with
      `predicted_a_beats_b` computed from `pre_comparison_probability` before the fit sees
      it → unit/integration test asserting the stored value
- [x] Live: open the comparison screen on real data, submit a judgment, confirm the queue
      reorders → **needs you**

## Approach

- New `web/routes.py` route(s), not `api/routes.py` — comparisons are an operator action
  with an HTML form, matching the established read-only-JSON/HTMX-HTML split (→ scouting
  F6)
- Opening/dimension selection is manual (dropdowns or similar) — no picker integration;
  `select_comparison` stays uncalled in production until a later node (→ scouting F15)
- Factor `_dimension_groups`/`digest_for_target` for two-opening reuse by calling the
  existing single-opening primitives twice, not rewriting them (→ scouting F5, F7)
- Wire `comparisons_by_target`/`companies_by_opening` into every `pool_for_screening` call
  in `web/routes.py` (queue and rating), not just a new comparison route — scouting F2's
  gap is in the shared assembly path (→ scouting F2)
- Queue page links to the comparison screen (→ scouting F8); no new nav surface beyond
  that link (open space)

## Not Doing

- `select_comparison`-driven suggestion flow — later node, once manual comparisons are
  proven to move rank correctly (→ scouting F15)
- Comparison history/audit view — the calibration log is queryable by later work if
  needed, not surfaced now (open space)

## Testing

Test-first by default. Exempt: nothing named yet.

## Recalibrate When

- If `_dimension_groups`/`digest_for_target` don't cleanly support two calls per render
  (e.g. hidden per-opening state), stop rather than forking the primitive (→ scouting F5).

## Agreed

- Manual pair/dimension selection, not the `select_comparison` suggestion flow — proves
  the fit-to-rank path before layering the picker on top (→ operator, scouting F15)
