---
feature: opening-lifecycle
type: bearing
date: 2026-09-09
commit: 93dd9c2
branch: round-peach
status: implemented
scouting: ./scouting.md
---

## Problem

Openings the operator has applied to, is pursuing through unconventional human contact, or
has heard back on (rejected/withdrawn) still clutter the ranked queue and still anchor the
top-5 boundary the bandit scores against. They need a lifecycle stage so they can be pulled
out of ranking while staying retrievable — the rulings and job descriptions remain useful
for calibration and future screening. Terrain: [scouting.md](./scouting.md)

## Done When

- [x] A new opening defaults to `screening`; `pursuing`, `applied`, `closed` are reachable
      from the rating view via a state-changing action.
      → `tests/store/test_store_repo.py::test_upsert_opening_persists_stage_change` +
      `tests/test_web.py::test_submit_stage_change_updates_opening_and_redirects_to_queue`.
- [x] The ranked queue (`/`, `/queue` JSON, `/contested`) and the research batch's
      candidate set include only `screening`-stage openings; `top_k`/boundary computation
      no longer includes a de-queued opening (→ scouting F16/F17).
      → `tests/test_web.py::test_queue_excludes_openings_not_in_screening_stage`,
      `::test_moving_opening_out_of_screening_drops_it_from_boundary_computation`,
      `tests/test_research_batch.py::test_batch_skips_openings_not_in_screening_stage`.
- [x] A filter-by-stage view exists so every non-`screening` opening is reachable and
      distinguishable by stage (→ scouting F15).
      → `tests/test_web.py::test_archive_view_lists_openings_by_stage`,
      `::test_archive_view_filters_to_one_stage_via_query_param`.
- [x] Stage never enters `ScoringConfig`/`ScoreResult`/the Monte Carlo trace (wall 3,
      same shape as obtainability).
      → no scorer/config file reads `Opening.stage`; the field is consumed only by
      `repo.list_openings`'s filter and the web layer.

## Approach

- `Opening` gains a `stage` field (`screening | pursuing | applied | closed`, default
  `screening`), stored via an additive migration (→ scouting F1, F2, F3 — same shape as
  migrations 0006/0007).
- `repo.list_openings` takes a stage filter (or a sibling function does) so the queue,
  `/queue`, `_scored_openings`, `_kth_result`, and `research/batch.py`'s candidate set all
  read through one filtered call rather than each re-implementing the exclusion (→
  scouting F17 — one change point, not three).
- The stage-change action is a plain POST-and-redirect route (`/openings/{id}/stage`) in
  `web/routes.py`, not an HTMX partial swap — changing stage typically removes the
  opening from the page the operator is looking at (the queue, or its own now-inapplicable
  rating context), so a redirect back to `/` fits better than the in-place swap
  `submit_ruling`/`submit_dimension_ruling` use for same-page updates.
- No `outcome` sub-field on `closed` — one terminal stage, no sub-typing (→ operator,
  scouting F18).

## Not Doing

- Outreach automation (finding blog-post authors, second-degree-connection lookup) — a
  later feature; this one only leaves `pursuing` as a state for it to eventually read
  (→ scouting F10).
- Any ranking, ordering, or VOI treatment of `pursuing`/`applied`/`closed` openings —
  these three states are purely "out of the live queue, still retrievable," no sub-model
  (→ operator, scouting F7).
- A note/summary field for "what I thought of it" — existing Ruling/Assertion history on
  the opening already answers that once it's reachable via the filter view (→ scouting F8).

## Testing

Test-first by default. No exemptions named.

## Recalibrate When

- The filter-by-stage view needs sorting/search beyond grouping by stage to be usable —
  stop, that's new scope.
- A future feature needs `pursuing` to carry outreach-attempt detail (contacts tried,
  blog posts found) — that's the outreach feature's bearing, not a retrofit here.

## Agreed

- Four stages, no ranking sub-model for three of them — the operator's own framing, not
  derived (→ scouting F7).
- No `outcome` enum on `closed` — deferred until a real need for the distinction shows up
  (→ scouting F18).
- Filter-by-stage is a real view, not just direct-URL retrieval — operator wants to browse
  de-queued openings by stage (→ scouting F15).
- De-queued openings must not anchor the `top_k` boundary — fixed at the shared
  `list_openings` call site, not per-caller (→ scouting F16/F17).
