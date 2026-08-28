---
feature: review-shell
type: bearing
date: 2026-08-28
commit: 56567fa5253ae6bc73fa867bdf6f4bd152301950
branch: main
parent: ../review-ux/scouting.md
status: done
scouting: ../review-ux/scouting.md
---

## Problem

review-ux (→ `../review-ux/scouting.md`) is the whole operator-review surface: triage,
rating, precedent, the eventual leverage/VOI-style rating signal. This bearing is its
first slice — the delivery shell everything else renders through: a queue view and a
separate rating surface. Not the Ruling data model (F6/F18 stay open, see Not Doing) and
not rating submission/HTMX resort (deferred until a ruling store exists).

## Done When

- [x] `GET /` (or equivalent) renders the ranked queue as HTML, computed from the same
      `score_opening`/`list_openings` calls `routes.py` already uses (→ F21)
      → new route returns 200 with `text/html`, queue order matches `GET /queue`'s JSON
- [x] The rating surface is a distinct route/template from the queue, not a modal bolted
      onto it (→ F19) → two templates exist, reachable by two paths
- [x] Existing JSON routes (`/openings/{id}/score`, `/queue`) are unchanged and still pass
      `tests/test_api.py`/`test_api_scoring.py` → test suite green

## Approach

- Server-rendered HTML via FastAPI's own `Jinja2Templates`/`HTMLResponse`, no second
  runtime — not a Svelte/Node stack, because this surface carries no client-side API
  contract while the domain model (Ruling granularity) is still moving (→ scouting F22)
- The rating surface is reachable as a distinct route/template; it is read-only for now
  because the Ruling data model is not landed (F6/F18) and the operator is not yet asking
  to capture rulings (→ scouting F19)
- New routes live under `src/screen/web/` (templates + view routes), separate from
  `src/screen/api/` (JSON) even though both may call the same domain functions — keeps the
  physical split "backend vs. presentation" visible without inventing a second package
  boundary for domain code (open space)
- Visual language starts from the prototype's band/fit chip vocabulary
  (`job-screener-prototype/static/app.css`), hand-written CSS, no component library yet
  (→ scouting F24)

## Not Doing

- Ruling data model / dimension-level Ruling granularity (F6/F18) — stays open, this
  bearing renders whatever shape exists today
- Rating-VOI/leverage-style triage (review-ux F3) — the next slice, builds on this shell
- Keyboard-driven triage, drag-reorder, undo-before-commit, or any client-only state (→
  scouting F23) — not on the near-term roadmap
- Adopting Skeleton/Svelte or any component library — revisit only if a specific
  interaction needs client state HTMX can't express (→ scouting F22)
- Fixing `intake/` importing `loop/` (cli.py) — separate thread, not this bearing's scope

## Testing

Test-first by default. Exempt:
- `src/screen/web/templates/` — Jinja templates have no unit-testable logic of their own;
  covered indirectly via route integration tests

## Recalibrate When

- A rating interaction needs state that must survive across two visible panels
  simultaneously (queue + rating surface on screen at once, not sequential pages) — HTMX
  alone doesn't model this (→ scouting F22)
- The Ruling data model lands (F6/F18) and we add submission/HTMX resort; the read-only
  route shape from this bearing should be reused, not re-built from scratch

## Agreed

- FastAPI stays; no Flask migration — `Jinja2Templates`/`HTMLResponse` are native to it,
  and the existing `Depends(get_db)` DI pattern applies unchanged to HTML routes (→
  scouting F21)
- Server-rendered + HTMX over Svelte+API, for now — reversal cost is asymmetric: HTMX
  carries no client contract to invalidate when the domain model moves; a typed
  Svelte/JSON split would (→ scouting F22)
- The "costing you" list (rich client state, animation, shared component library) is
  explicitly not a hedge to design around — nothing on it is on the near-term roadmap (→
  scouting F23)
