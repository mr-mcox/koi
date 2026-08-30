---
feature: review-ux
type: bearing
date: 2026-08-31
commit: 10eda09
branch: main
status: done
parent: ./scouting.md
scouting: ./rating-voi-scouting.md
---

## Problem

Ratings have gone from pets (one exciting opening at a time) to cattle (10+ intake'd
openings, most only partly rated). The operator needs the rating surface to direct
DimensionRuling is the tip of the work to be done before 
attention rather than present everything: per opening, pick the handful of unrated
assertion/dimension-ruling tasks that would collectively move its score the most, and
present only those in a focused view before moving to the next opening. Terrain:
[rating-voi-scouting.md](./rating-voi-scouting.md).

## Done When

- [x] Given an opening with unrated assertions/dimensions, a function returns the
      task budget (3-4, configured) ranked by estimated score movement — test: a target
      with wide half-width and high dimension weight/constraint leverage outranks a
      narrow, low-weight one (→ scouting F54, F50)
- [x] A focused rating view for one opening renders only the budgeted tasks (each with its
      digest/citations/context) and hides other assertions/dimension groups on that
      opening — test: route response contains only the selected targets' rows (→ scouting
      F60, F61)
- [x] Submitting a task's rating (assertion or dimension ruling) updates the same focused
      view via HTMX partial swap, consistent with the existing ruling-submit contract —
      no full reload (→ scouting F63, review-ux/scouting F20)
- [x] The per-opening task budget is a named value in `scoring.yaml`, not a literal (→
      scoring.yaml precedent, AGENTS.md "measure before model")
- [x] Existing `rate` (full) page, JSON routes, and queue are unchanged and still pass
      their tests (→ scouting F63)
- [x] The focused view's task set is stable for the duration of one focus session (a
      completed task doesn't vanish when a second task is completed, and no new task
      appears mid-session) — reload or moving to the next opening is the only way the
      task set changes (→ operator live-feedback, this session)
- [x] The focused view respects a presentation hierarchy: a task at a lower level
      (assertion) never fully hides the level above it in a way that blocks correcting
      it, and a task at a higher level (dimension) never fully hides the assertions
      beneath it — collapsed, not removed (→ operator live-feedback, this session)

## Approach

- Arm = opening, task = one unrated assertion or one unrated dimension-target on that
  opening (→ scouting F57, operator)
- Per-item leverage proxy: for each unrated item's target, compare current `_TargetStats`
  against the stats if that one item were resolved favourably (reusing the reach
  counterfactual's resolve-one-target shape from `resolve_favourably`) and rank by the
  resulting standing delta; select the top N up to the configured budget — reuses the
  Scorer's existing seam, no new data model (→ scouting F54, F62)
- The budget selection and any displayed "leverage" number are display/route-layer only,
  computed by calling `score()` repeatedly with different single-item overrides — never
  written back as a field on `Assertion`/`DimensionRuling` (→ scouting F49, decisions S8)
- Guard against sampling-noise-driven ranking: use a fixed, shared seed across the
  comparison calls for one opening (same as `config.seed` already is) so ranking is
  reproducible; if two candidates' deltas are within a few `p_stderr`s, order between them
  is not asserted as meaningful (→ scouting F55)
- New route (e.g. `/openings/{id}/focus`) reusing `_rating_context`'s data assembly,
  filtered to the budgeted targets, same template family as `rating.html` (→ scouting
  F61, Not Yet Settled on template reuse — implementer's call)

## Not Doing

- Pre-intake backlog triage (which of the 10+ leads get a research pass) — intake is
  cheap; out of scope (→ scouting F56, operator)
- Cross-opening explore/exploit sequencing (which opening to focus on next) — this bearing
  ranks tasks *within* one opening; choosing the next opening is a smaller, separate
  concern not blocked by this one
- Any change to `Scorer.score()`'s public contract, `Target`, or persisted rulings shape —
  ranking is read-only computation over existing data (→ scouting F59)
- Curved/precise numeric display of "how much this would move things" — a rank order and
  a band-style display, not a decimal (AGENTS.md "no unearned precision")

## Testing

Test-first by default. Exempt:
- Any new focused-view template — Jinja, no unit-testable logic of its own, covered by
  route integration tests (same exemption as `rating.html`)

## Recalibrate When

- The per-item leverage proxy can't be computed as independent single-item deltas because
  items interact non-additively in a way that matters — stop, "collectively" needs a real
  combinatorial evaluation, not a sum of marginals
- Candidate deltas are consistently within Monte Carlo noise of each other across real
  openings — stop, the ranking isn't distinguishing anything and the mechanism needs
  rework (→ scouting F55)

## Agreed

- Scope is already-intake'd openings only; pre-intake triage is a separate, deferred
  question (→ scouting F56, operator)
- The bandit's arm is the opening; switching cost is a per-opening task budget (3-4 items),
  not a formula weight or a UI lockout mechanic (→ scouting F58, operator)
- A focused view hides everything except the budgeted tasks, with enough context per task
  to rate it — not the full rating page filtered visually, an actually reduced surface (→
  scouting F60, operator)
- Presentation hierarchy: dimension > assertion. A budgeted assertion task may hide its
  parent dimension's digest/pad; a budgeted dimension task must keep its assertions
  reachable (collapsed, not removed) — the operator must always be able to correct a
  lower-level judgment that's the real reason a higher-level one looks wrong (→ operator
  live-feedback, this session)
- No new persisted state was needed for the hierarchy/stability fixes — `Assertion`,
  `AssertionRuling`, `DimensionRuling`, and `RatingTaskCandidate` were already sufficient;
  the friction was route/template conflation of "budgeted" with "visible," and of
  "recomputed" with "stable" (→ operator live-feedback, this session)
- The focused view's task set is a snapshot taken at the initial GET and echoed back via
  hidden fields on every HTMX submit, not recomputed after each submission — a real UI
  session needs the screen to hold still, not just show correct output at each step (→
  operator live-feedback, this session)
