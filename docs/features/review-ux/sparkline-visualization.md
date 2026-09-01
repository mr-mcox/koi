---
feature: review-ux
type: bearing
date: 2026-08-31
commit: efe0c2d
branch: main
status: orienting
parent: ../review-ux/scouting.md
scouting: ./sort-and-presentation-scouting.md
---

## Problem

The per-opening score block (`standing 0.018 / reach 0.022 / ceiling 0.791`) and the
queue's raw `standing` float are noise, not signal, and are a direct violation of the
"precision ranks, bands display" wall. A stale, unbuilt bearing
(`dimension-ruling-flat-gradient.md`) already worked out a flat-band visual for one
dimension's `(mean, half_width)`; this leaf generalizes that shape into a compact
sparkline-style glyph for **both** the queue (one row per opening) and the per-opening
view (replacing the raw numbers), so the operator sees relative spread and position
without a decimal. Terrain:
[sort-and-presentation-scouting.md](./sort-and-presentation-scouting.md) F3, F7, F8, F9,
F10.

## Done When

- [ ] The per-opening score block no longer renders `standing`/`reach`/`ceiling` as
      formatted floats — test: `_rating_content.html` render contains no `%.3f` value for
      these fields (→ scouting F3)
- [ ] The queue no longer renders raw `standing` as a formatted float per row — same test
      shape against `queue.html` (→ scouting F3)
- [ ] Both the queue row and the per-opening view render a sparkline-style glyph built from
      the same `(mean, half_width)` pair the Scorer samples from — test: the rendered glyph's
      numeric endpoints match `_stats_for_target`/`ScoreResult` for a synthetic opening (→
      scouting F8, F9)
- [ ] The glyph visually distinguishes *why* a target is wide: unexamined prior vs. a
      `DimensionRuling` pin vs. assertion disagreement — test: three synthetic cases render
      distinct visual states (→ scouting F7)
- [ ] `standing` remains the only sort key; the glyph is display-only and never becomes an
      input to sorting or scoring (→ scouting F6)

## Approach

- Queue-level glyph summarizes the opening's `standing`/`reach` pair (not a per-dimension
  breakdown — that's the per-opening view's job); per-opening glyphs are per-target,
  reusing `dimension-ruling-flat-gradient.md`'s Approach almost unchanged: CSS
  `linear-gradient`, flat (not curved), computed from `_stats_for_target`, low opacity (→
  scouting F8, F9)
- Reuse `_stats_for_target` as the seam for per-opening/per-target glyphs, same as the
  stale bearing specified; queue-level glyph is a new, smaller computation over
  `ScoreResult` (standing, reach, ceiling) rather than per-target stats (→ scouting F9)
- Distinguishing "wide because unexamined" from "wide because pinned" from "wide because
  disagreement" is a new visual requirement the stale bearing didn't have (it only handled
  pinned vs. unpinned) — needs a third visual state, not just color/opacity tuning (→
  scouting F7)

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

- The flat mean/half-width glyph is ambiguous often enough in practice that the operator
  can't tell wide-and-unexamined from wide-and-pinned — stop, F7's why-it's-wide
  distinction is no longer deferrable (→ scouting F7)

## Agreed

- Build for both the queue and the per-opening view, not one first — same visual language
  reused at two scales (→ operator, this session)
 implying false precision — stop, the visual language needs rework before
  shipping (→ scouting F7)
- This glyph turns out to also settle the band-label-clarity leaf (i.e., the sparkline
  makes the categorical labels redundant) — stop and fold that leaf in rather than building
  it separately (→ operator, this session: "sparklines would be possible replacement")

## Agreed

- Build for both the queue and the per-opening view, not one first — same visual language
  reused at two scales (→ operator, this session)
