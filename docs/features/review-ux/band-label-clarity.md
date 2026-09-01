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

Once `sparkline-visualization.md` lands, the five categorical band labels
(`no path`/`contender`/`established`/`capped`/`wide open`) are largely superseded by the
glyph — the operator's framing: "if sparkline is in place, band label clarity is just
cleanup." This leaf removes the now-dead categorical display rather than trying to fix
its blurry thresholds. Terrain:
[sort-and-presentation-scouting.md](./sort-and-presentation-scouting.md) F4, F5, F11.

## Done When

- [ ] The four cosmetic branches of `band_for` (`contender`/`established`/`capped`/`wide
      open`) and their `scoring.yaml` thresholds (`bands.contender/settled/reach_capped/
      reach_wide`) are removed from display — test: rendered queue/rating pages no longer
      contain a `band-{contender,established,capped,wide-open}` CSS class (→ scouting F4)
- [ ] The `unreachable` ("no path" / over-the-cliff) case is kept as a labeled state — it's
      structural (S4: analytic ceiling, not a display dial), not a dial being retired (→
      scouting F4, S4)
- [ ] `standing`/`reach` remain computed and available wherever the sparkline glyph needs
      them; only the categorical band's cosmetic branches and unused CSS are deleted (→
      scouting F6)

## Approach

- Delete, don't replace — this is cleanup following the sparkline glyph, not a new
  labeling scheme (→ operator, this session: "just cleanup")
- `band_for`'s signature/return type may need to narrow (fewer `Band` string values) —
  check callers before removing, since `Band` is consumed by templates and possibly tests
  beyond the two removed here (open space)

## Not Doing

- Any new legend/tooltip/explanation UI for band meaning — moot once labels are removed
- Retuning `bar` or any surviving threshold — separate, unmeasured dial (open-questions.md
  #9)

## Testing

Test-first by default. Exempt: nothing.

## Recalibrate When

- The sparkline glyph (once live) turns out not to communicate "no path" clearly on its
  own — stop, `unreachable` may need more than a bare label (→ scouting F4)
- Removing the four cosmetic bands breaks a test or caller not yet accounted for in Done
  When — stop and re-scope rather than force the deletion through (open space)

## Agreed

- Sequenced strictly after `sparkline-visualization.md` — this leaf doesn't start until
  that one's Done When is met (→ operator, this session)
- Scope is deletion of dead display code, not a redesigned taxonomy (→ operator, this
  session)
