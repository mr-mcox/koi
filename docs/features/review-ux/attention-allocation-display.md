---
feature: review-ux
type: bearing
date: 2026-09-02
commit: 3edace7
branch: main
status: implementing
scouting: ./attention-allocation-display-scouting.md
---

## Problem

The queue's three-point lollipop (`standing`/`reach`/`ceiling`) saturates and compresses the
mid-pack because `ceiling` clusters at 1.0 and the score axis is scaled to it. The operator
needs a single glanceable glyph that tells them whether an opening is confidently above,
confidently below, or still contesting the top-K boundary, so attention is routed to the
contested ones. The crossing-probability computation already exists; only the rendering
is missing. Terrain: [attention-allocation-display-scouting.md](./attention-allocation-display-scouting.md).

## Done When

- [x] The queue row renders a single score-axis glyph replacing the lollipop: a dot at
      `median(overall trace)`, a symmetric credible interval around it (q10/q90 from the
      Monte Carlo trace), and a vertical tick at the K-th opening's `median(overall trace)`
      — test: `queue.html` contains no `sparkline-*` CSS classes and no `reach`/`ceiling`
      labels (→ F11, F16, this session's correction below)
- [x] The per-opening score block uses the same glyph shape as the queue row: the
      interval bar (low/high as its own edges, this session's correction below), the
      median dot, and the boundary tick — test: `_rating_content.html` shares the
      macro with `queue.html` and shows the same marks for a synthetic opening
      (→ F16)
- [x] The old `Sparkline` dataclass and `_sparkline.html` macro are removed entirely; no
      route or template still references `reach`/`ceiling` for display — test: `grep -R
      sparkline\|Sparkline\|\.reach\|\.ceiling src/screen/web/templates src/screen/api` in
      display contexts returns nothing (→ F17)
- [x] The JSON `/queue` response still includes the existing `crossing_probability` field
      untouched, so the new glyph is display-only and does not alter the API contract
      (→ attention-allocation-computation.md, F2)
- [x] Openings with fewer than `top_k` scored openings show no boundary tick and no
      contest shading — the boundary does not exist yet (→ attention-allocation-scouting.md
      F33, attention-allocation-computation.md Approach)

## Approach

- Replace the lollipop with a **credible-interval bar on a score axis**: a dot at
  `median(overall trace)`, a horizontal bar from `low` to `high` derived from the trace
  quantiles, and a vertical tick at the K-th opening's `median(overall trace)` (the
  boundary) — all three marks on the same `overall`-quality axis (0-1), never on the
  `P(> bar)` axis `standing` lives on. **Correction, this session:** the dot was originally
  specified as `standing` itself, but `standing = P(overall > bar)` is a single scalar per
  `ScoreResult`, not a per-draw quantity — `np.quantile(trace, .1/.9)` lives on the `overall`
  axis and does not bracket `standing` (checked against three scoring scenarios: unexamined,
  partially-researched, fully-researched — the interval missed `standing` in all three).
  `median(trace)` is the trace statistic that the quantile interval actually brackets by
  construction, so it is the dot instead. This is a display-only change either way;
  `standing` remains the sort key and `reach` continues to drive the research/rating bandit
  pre-filter (S5, F6) — nothing about ranking or the bandit changes, only what is plotted.
- Use a **symmetric trace quantile interval** (e.g., q10/q90) for `low`/`high`. It is derived
  from the same `ScoreResult.trace` already produced for every opening; no extra sampling
  and no new scoring primitive (→ F12, F2). The quantile pair is a display convention, not a
  model parameter; start with it as a code constant and only promote it to `scoring.yaml` if
  real use shows the need to tune it (open space).
- Render the boundary as a **single vertical tick** at the K-th opening's
  `median(overall trace)`, not an interval. The K-th opening is a fixed scalar reference;
  giving it its own uncertainty band would duplicate the fixed-reference caveat already
  tracked in the recalibration trigger (→ F14, attention-allocation-computation.md
  Recalibrate When). `crossing_probability` itself is untouched by this session's
  correction — it already compares `trace_i > trace_kth` elementwise on the `overall` axis,
  never touching `standing`; only the tick's *plotted position* moves from `standing` to
  `median(trace)`.
- Share the same glyph macro and shape between the queue row and the per-opening score
  block, and use a **single fixed 0-1 scale in both views**. The original plan called for a
  context-relative queue scale to counter `ceiling` clustering at 1.0 (F16); with the dot now
  on the `overall` axis instead of a `ceiling`-scaled `standing`, that clustering doesn't
  happen — checked across four scoring scenarios (unexamined through fully-researched), the
  median spread runs ~4%-30% of a fixed 0-1 axis, not compressed at one end. One scale, no
  per-view `scale_max` parameter.
- Drop numeric labels in the queue row. In the per-opening block, the crossing probability
  is available only as a **tooltip** (title attribute or similar) — no visible number, no
  chartjunk. Visual position is the primary read; the number is there only if inspected (→ F15).
- No separate end-cap markers for `low`/`high` — the horizontal bar's own left/right
  edges already carry that information; a marker at each end was redundant chartjunk
  (operator feedback, this session). Only the median dot and the boundary tick are
  discrete marks; `low`/`high` remain named fields on `BoundaryGlyph` (the bar geometry
  is still computed from them), just not rendered as their own spans.

## Not Doing

- A separate probability-meter bar or color-only side encoding — the operator wants left/right
  to be actual left/right on the score axis (→ F11)
- A resampled or pairwise boundary comparison — the fixed K-th reference approximation from the
  computation leaf stands (attention-allocation-computation.md Approach, Recalibrate When)
- Displaying `reach` or `ceiling` in any form — both are replaced by the trace quantile
  interval and the boundary tick (→ F11)
- Pipeline-stage filtering to exclude applied openings — the computation leaf explicitly
  deferred this (attention-allocation-scouting.md F32); the boundary view runs over the full
  backlog until that slice is built separately
- A per-view `scale_max` — superseded by this session's fixed-0-1-axis correction above;
  `standing`'s `ceiling`-relative scaling doesn't apply once the dot is `median(trace)`

## Testing
Test-first by default. Exempt:
- The new Jinja macro shape and CSS — the visual glyph has no unit-testable logic; covered by
  route integration tests that assert the bar/dot/tick marks and the absence of old lollipop artifacts
  (same exemption as `sparkline-visualization.md` for templates)

## Recalibrate When

- The q10/q90 interval looks too wide or too narrow on real queue data, making too many
  openings look contested or too few — stop and tune the quantile pair before declaring the
  visual language done (→ F12)
- The fixed 0-1 scale compresses the mid-pack after all on real queue data (the failure
  mode this session's correction was meant to avoid) — stop and reconsider a context-
  relative scale, this time on the `overall`/median axis rather than `standing`/`ceiling`
  (→ F16)
- The operator wants a visible (non-tooltip) numeric crossing probability instead of the
  interval-vs-boundary read — stop and promote it, treating it as a signal the visual
  encoding is failing (→ F15)
- Real queue data shows the K-th opening's identity churning turn-to-turn so that the fixed
  boundary tick is misleading — stop, this is the same recalibration trigger as the
  computation leaf (attention-allocation-computation.md Recalibrate When)

## Agreed

- Left/right must be actual left/right on the score axis, not a color or separate meter
  (→ F11)
- The probability is the fraction of the trace above/below the top-K boundary; the credible
  interval displays this geometrically, so the displayed shape and the action are the same
  thing (→ F12)
- Same glyph representation and the same fixed 0-1 scale for the queue row and the
  per-opening score block — this session's correction dropped the per-view `scale_max`
  (→ F16)
- `reach` and `ceiling` are removed from the display glyph entirely; they remain in the model
  for the research/rating bandit pre-filter and the `unreachable` analytic check (→ F6, F11)
- The crossing probability is a tooltip only in both views, never a visible number — visual
  position is the primary read, no chartjunk (→ F15)
- The quantile pair starts as a code constant, not a config value; promote only if measured
  need (→ F12)
