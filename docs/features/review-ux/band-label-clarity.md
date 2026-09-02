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
cleanup." Widened this session: the operator wants **all five** labels gone, including
`no path`/`unreachable` — no categorical text, no colored chip, anywhere. `unreachable`
stays computed (S4: analytic ceiling, not sampled) and still affects grouping/sorting, but
it is not rendered as a label. Terrain:
[sort-and-presentation-scouting.md](./sort-and-presentation-scouting.md) F4, F5, F11;
this session's conversation on S4.

## Done When

- [ ] `band_for` and its `Band` return type are deleted entirely — no function anywhere
      derives a categorical label (`no path`/`contender`/`established`/`capped`/`wide
      open`) from `standing`/`reach` — test: `band.py` no longer exists / exports nothing
      band-shaped (→ scouting F4, operator this session: "get rid of all of them")
- [ ] The four cosmetic thresholds (`scoring.yaml`'s `bands.contender/settled/
      reach_capped/reach_wide`) are removed from config — test: `ScoringConfig`/`Bands`
      carries no cosmetic threshold fields (→ scouting F4, F5)
- [ ] No queue or rating-page row renders a band chip or band text of any kind — test:
      rendered pages contain no `band-*` CSS class and no band label string (→ scouting F4)
- [ ] `unreachable` remains a computed property on `ScoreResult` (S4: analytic ceiling, not
      sampled) and continues to gate whatever grouping/sorting already depends on it — only
      its *label* is deleted, not the computation (→ S4, operator this session: "keep it
      computed, stop rendering a categorical word for it")
- [ ] `standing`/`reach`/`ceiling` remain computed and available wherever the sparkline
      glyph needs them; only band labels and their CSS/config are deleted (→ scouting F6)

## Approach

- Delete, don't replace — this is cleanup following the sparkline glyph, not a new
  labeling scheme (→ operator, this session: "just cleanup")
- `band_for`'s return type (`Band`) is retired along with the function itself, not
  narrowed — every caller of `.band` (JSON response, both templates) is updated in this
  leaf, since keeping a narrower `Band` alive would keep a categorical concept the operator
  explicitly wants gone
- Full deletion touches more than the queue/rating templates: `OpeningScore.band`
  (`src/screen/api/scoring.py`) and `ScoreResponse.band` (`src/screen/api/routes.py:44`)
  are both real fields consumed by the JSON API, not just server-rendered HTML — remove the
  field from both, and from the JSON contract, rather than leaving it populated with
  nothing to show (→ this session's read of `routes.py`)
- `queue.html`/`_rating_content.html` currently key their outer `<li>`/chip CSS class off
  `item.band`/`score.band` (`band-{{ ... }}`) — that styling hook goes away with the field;
  if a visual distinction for `unreachable` rows is still wanted, it needs a new,
  non-band-named hook (e.g. a boolean CSS modifier), not a revived label (open space)

## Not Doing

- Any new legend/tooltip/explanation UI for band meaning — moot once labels are removed
- Retuning `bar` or any surviving threshold — separate, unmeasured dial (open-questions.md
  #9)

## Testing

Test-first by default. Exempt: nothing.

## Recalibrate When

- Deleting `unreachable`'s label turns out to make over-the-cliff openings genuinely hard
  to distinguish from low-standing-but-live ones in the queue — stop, this reopens whether
  S4 needs *some* non-categorical signal (e.g., a muted row style, a grouping, or a fixed
  bar reference on the sparkline), not necessarily a text label (→ operator this session)
- Removing all five bands breaks a test or caller not yet accounted for in Done When —
  stop and re-scope rather than force the deletion through (open space)

## Agreed

- Sequenced strictly after `sparkline-visualization.md` — this leaf doesn't start until
  that one's Done When is met (→ operator, this session)
- Scope widened this session, still cleanup: delete all five categorical labels, including
  `no path`/`unreachable` — not a redesigned taxonomy, and not a replacement label scheme
  (→ operator, this session: "get rid of all of them")
- The 95%-ceiling sparkline-scaling idea and the cross-opening attention-allocation signals
  (research-pass bandit, rating bandit) discussed this session are explicitly out of this
  leaf — tracked separately in `attention-allocation-scouting.md` (→ operator, this session)
