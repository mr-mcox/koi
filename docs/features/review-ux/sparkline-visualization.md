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

The per-opening score block (`standing 0.018 / reach 0.022 / ceiling 0.791`) and the
queue's raw `standing` float are noise, not signal, and are a direct violation of the
"precision ranks, bands display" wall. A stale, unbuilt bearing
(`dimension-ruling-flat-gradient.md`) already worked out a flat-band visual for one
dimension's `(mean, half_width)`; this leaf replaces the raw numbers with a compact
three-point lollipop glyph (standing, reach, ceiling) for **both** the queue (one row per
opening) and the per-opening view, so the operator sees relative spread and position
without a decimal. The horizontal axis is scaled to the largest ceiling in the current
context so the glyph fills the available space. Terrain:
[sort-and-presentation-scouting.md](./sort-and-presentation-scouting.md) F3, F7, F8, F9,
F10.

## Done When

- [ ] The per-opening score block no longer renders `standing`/`reach`/`ceiling` as
      formatted floats — test: `_rating_content.html` render contains no `%.3f` value for
      these fields (→ scouting F3)
- [ ] The queue no longer renders raw `standing` as a formatted float per row — same test
      shape against `queue.html` (→ scouting F3)
- [ ] Both the queue row and the per-opening score block render a minimalist lollipop glyph
      showing `standing`, `reach`, and `ceiling` on a horizontal axis scaled to the maximum
      ceiling in the current context — test: the rendered dot and range positions match the
      `score_opening` result for a synthetic opening (→ scouting F8, F9)
- [ ] `standing` remains the only sort key; the glyph is display-only and never becomes an
      input to sorting or scoring (→ scouting F6)

## Approach

- Both the queue row and the per-opening score block use the same opening-level lollipop
  component, computed from `standing`/`reach`/`ceiling` returned by `score_opening`. The
  horizontal axis is scaled to the largest ceiling in the current context (queue-wide max
  for the queue; the opening's own ceiling for the per-opening view) so the glyph fills the
  available space and still reads as a probability ruler. Start identical; allow
  context-specific CSS only if a single rendering looks wrong at one scale (→
  scouting F8, F9, operator this session)
- Per-target / per-dimension sparklines are out of scope for this leaf; they are recorded in
  `sort-and-presentation-scouting.md` F8/F9 and can become a separate bearing (→ operator)
- Promote `_stats_for_target` / `_TargetStats` in `scorer.py` to public names so the web route
  can read per-target distributions if the future dimension-bearing needs it; for this leaf
  they are only used to compute the opening-level lollipop via `score_opening` (→ operator
  this session, open space: whether the public types move to `score.types` or stay in
  `scorer.py`)
- Drop the "why it's wide" visual-state requirement: the operator doesn't need to decode
  unexamined vs. pinned vs. disagreement from the glyph alone; the dimension row already
  shows the pin control and provenance glyphs for that (→ operator this session)

## Not Doing

- Redesigning the five-label band taxonomy or its thresholds — separate leaf (→ scouting
  F4, F5)
- The queue-ruling sort-bug fix — ships alone, already a separate bearing (→ operator)
- Interactive/hover drill-down beyond a static glyph — no client-side interaction budget
  spent here (consistent with scouting.md F23's existing no-JS-framework stance)

## Testing

Test-first by default. Exempt:
- Any new/changed Jinja template — no unit-testable logic of its own, covered by route
  integration tests (same exemption as existing templates)

## Recalibrate When

- The lollipop or its scaled axis starts implying false precision or making openings look
  more similar than they are — stop, the visual language needs rework before shipping
  (→ scouting F7)
- The single shared component renders badly at one scale and needs to diverge, or the
  queue and per-opening scales need to unify — stop, if divergence is more than CSS it
  becomes a separate design question (→ operator)

## Agreed

- Build for both the queue and the per-opening view, not one first — same visual language
  reused at two scales (→ operator, this session)
- This glyph turns out to also settle the band-label-clarity leaf (i.e., the sparkline
  makes the categorical labels redundant) — stop and fold that leaf in rather than building
  it separately (→ operator, this session: "sparklines would be possible replacement")