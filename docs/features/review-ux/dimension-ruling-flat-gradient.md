---
feature: review-ux
type: bearing
date: 2026-08-30
commit: dafddc0
branch: main
status: proposed
parent: ./dimension-ruling.md
scouting: ./dimension-ruling-flat-gradient-scouting.md
---

## Problem

`DimensionRuling` pins each dimension to a continuous `(fit, settledness)` pair. The
Scorer already represents that pin as a flat uniform distribution over the interval
`[mean - half_width, mean + half_width]`. The review UI currently shows only the two
point numbers (mean and conviction) and a single-needle glyph, which understates the
uncertainty the model actually carries. The operator should be able to see the
implied spread at a glance, and compare it against the spread implied by the underlying
assertions before the pin was applied.

## Done When

- [ ] The rating page renders a subtle horizontal band behind each dimension's ruling
      control, spanning the interval the Scorer would sample from for that target.
- [ ] The band is visually distinct for the two cases:
      - pinned target: uses the `DimensionRuling`-derived `mean` and `half_width`
      - unpinned target: uses the assertions-derived `_TargetStats` (or the unexamined
        prior `mean=0, half_width=1`).
- [ ] The band color encodes value (e.g., red-left / green-right, or a neutral gradient)
      and is faint enough that the digest text and controls remain readable over it.
- [ ] The same rendering logic can be reused for constraints and dimensions without a
      separate code path.
- [ ] Existing single-click 2D pin submission and assertion-ruling behavior are unchanged.

## Approach

- Expose a public, serializable representation of `_TargetStats` from `screen.score.scorer`
  (or compute it in the route layer) so the web template receives, per group, the
  `(mean, half_width)` pair that the Scorer will sample from. The clean seam is to reuse
  `_stats_for_target`, which already applies the dimension-ruling override and returns
  `_TargetStats`. This keeps the route/template honest: the UI band is exactly the
  distribution the scorer uses.
- Pass a `target_stats` mapping through `_rating_context` / `_dimension_groups` so each
  `_DimensionGroup` carries both its `digest` and its `stats`.
- Render the band as a CSS `linear-gradient` on the dimension row background, positioned
  so the left edge corresponds to `mean - half_width` and the right edge to
  `mean + half_width`, clipped to `[-1, 1]` (the model's full fit scale). The color stops
  should map the same fit-to-color scale the assertion fit buttons already use:
  `Poor`/`red` at -1, `Mixed`/`yellow` at 0, `Strong`/`green` at +1. Keep opacity low
  (`0.15-0.25`) so the band reads as context, not as the primary verdict.
- For the gradient computation, prefer a template-side calculation over JS so the
  server-rendered / HTMX-swap contract stays intact. The CSS gradient is computed from
  the two numbers, not drawn from samples.

## Not Doing

- Curved / non-uniform distribution rendering (e.g., Gaussian curves, kernel densities).
  The Scorer's dimension samples are uniform over the interval; rendering anything other
  than a flat band would imply precision the model does not have.
- Interactive dragging inside the band itself. The band is read-only context; the pin
  control is still the 2D click-pad.
- Any new data persistence or new route. This is a display-only enhancement.

## Testing

- Test-first by default: add a scorer test that `_stats_for_target` returns the same
  stats for pinned and unpinned targets that the full `score()` uses, so the template
  cannot drift from the sampler. Add a web test that a rendered dimension group contains
  the expected gradient `background` style for a pinned target and for an unpinned target.
- Exempt: the exact visual appearance (color, opacity, positioning) is a CSS/template
  judgment call not unit-testable; the test checks that the computed numeric endpoints are
  present in the style attribute.

## Recalibrate When

- The band rendering requires sampling or re-implementing the scorer math in the template
  — stop, the seam should be `_stats_for_target`, not duplication.
- The gradient is too visually dominant and competes with the ruling control or the digest
  — stop, opacity/positioning needs rework before shipping.
