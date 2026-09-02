---
feature: review-ux
type: bearing
date: 2026-09-01
commit: b071c22
branch: main
status: implementing
parent: ./attention-allocation.md
scouting: ./attention-allocation-scouting.md
---

## Problem

Compute and expose `P(rank crosses K)` per opening, and retire the raw-swing `/focus`
entry point it replaces. Display is a separate leaf — this one is the stable, testable
math and wiring. Terrain: [attention-allocation-scouting.md](./attention-allocation-scouting.md).

## Done When

- [ ] A pure function `(ScoreResult, kth_result) -> float` returns the fraction of samples
      where the opening's `overall` trace exceeds the K-th-ranked opening's `overall`
      trace — test: for two synthetic `ScoreResult`s built from disjoint trace ranges, the
      function returns 0.0 or 1.0; for overlapping ranges, a mid-range value (→ scouting
      F33)
- [ ] `top_k` is a named value in `scoring.yaml`, not a literal (→ scoring.yaml precedent,
      AGENTS.md "measure before model")
- [ ] The JSON `/queue` route includes the crossing-probability value per opening,
      computed against the current queue's K-th-ranked opening under the shared
      `config.seed` — test: two calls against the same DB snapshot return identical values
      (→ scouting F33, F16)
- [ ] `_focus_queue_items`, `_opening_leverage`, the `/focus` redirect route, and
      `queue.html`'s "Start focused rating session" link are removed — the raw-swing
      cross-opening ranking they implement is superseded by the crossing-probability
      signal (→ scouting F26, F28). The per-opening `/openings/{id}/focus` route,
      `rating.html`'s focus-mode rendering, and `rating_task_candidates` are **untouched**
      — that is `rating-voi-triage.md`'s already-`done` within-opening task budget, not in
      tension with this leaf — test: `tests/test_web.py`'s
      `test_focus_opening_shows_only_budgeted_tasks` and sibling per-opening focus tests
      still pass unmodified; only the `test_focus_redirect_*` tests (cross-opening entry
      point) are removed
- [ ] Existing JSON `/queue` and per-opening rating tests otherwise pass unmodified (→
      scouting F16)

## Approach

- Fewer than K openings in the queue: no K-th opening exists, so every opening's
  crossing-probability is undefined/not shown rather than defaulting to 0 or 1 — a small
  backlog isn't "everyone stable," it's "the boundary doesn't exist yet" (open space)
- Reuse `ScoreResult.trace` directly; no new sampling call, no new Scorer type — the
  comparison lives in `screen/score/` alongside `triage.py` as a sibling pure function,
  or in the route layer if it turns out to need no state beyond two `ScoreResult`s
  (open space — implementer's call, mirrors `triage.py`'s existing seam)
- `top_k` lives in `scoring.yaml` next to `bar`/`rating_task_budget`, same
  unmeasured-placeholder status (→ scoring.yaml precedent)

## Not Doing

- Any display change to `queue.html` beyond removing the two `focus` links — the glyph
  for the new value is the sibling display leaf's job
- A pairwise or resampled multi-opening boundary comparison (→ scouting F30, F33)
- Touching `rating_task_candidates`, `_swing`, or anything under `triage.py` — those
  remain the within-opening rating-VOI mechanism, untouched by this leaf

## Testing

Test-first by default. Exempt: nothing.

## Recalibrate When

- Real queue data shows rank K's identity churning turn-to-turn such that the fixed
  K-th-trace reference materially misrepresents crossing probability — stop (→ scouting
  F33, parent Recalibrate When)

## Agreed

- The per-opening `/openings/{id}/focus` rating surface is out of scope and explicitly
  preserved — only the cross-opening `/focus` entry point and its raw-swing ranking are
  dead weight (this session)
