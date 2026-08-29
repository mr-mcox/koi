---
feature: review-ux
type: scouting
date: 2026-08-30
commit: dafddc0
parent: ./scouting.md
---

## What We're Doing

`docs/CURRENT.md`: "DimensionRuling is the tip of the work to be done before VOI-style
triage can be applied." F31 (parent scouting) had deferred `DimensionRuling` until an
assertion-level corpus existed; the operator has since moved the tip here, so that
deferral is superseded — this is the terrain for building it now, mirroring the
`assertion-rating-layout` / `assertion-ruling-submit` split that already shipped for
assertion-level ratings.

## Findings

- **F34** — `data/live/screen.db` — real corpus exists: 52 assertions, 10
  `assertion_rulings`, across 5 openings. F31's stated precondition (assertion-level
  corpus) is met.
- **F35** — `src/screen/score/scorer.py:52-67` (`_target_stats`) — every scoring
  dimension and constraint already reduces to exactly two numbers before sampling:
  `mean` and `half_width`. A `DimensionRuling` that pins `(fit, settledness)` per F27
  has an exact slot to substitute into — no new scorer shape needed, just a second
  override source at the same seam `rulings: dict[str, Fit]` already uses for
  `AssertionRuling` (`scorer.py:99-108`, `score()`'s `rulings` parameter).
- **F36** — `src/screen/score/scorer.py:99-108` — `score()` currently takes one
  optional override (`rulings: dict[str, Fit]`, assertion-id keyed) and threads it into
  `_target_stats` per-assertion. A `DimensionRuling` override is target-keyed and
  replaces the *whole* computed `_TargetStats`, not one assertion's fit value inside the
  sum — a structurally different parameter, not a variant of the existing one.
  Precedence when both exist: a `DimensionRuling` is the aggregate judgment "given all
  of the underlying assertions & rulings" (domain-model.md §Ruling), so it supersedes
  the assertion-level computation for that target entirely, per-assertion rulings and
  all.
- **F37** — `src/screen/score/types.py:19-32` (`ConstraintRange`) — constraints
  affine-map `_TargetStats.mean/half_width` onto a tolerability range before sampling
  (`scorer.py:82-88`, `_sample_constraint`). A `DimensionRuling` pin must work for both
  scoring dimensions and constraints — same substitution point (`_TargetStats`), so no
  separate code path is needed per target kind.
- **F38** — `src/screen/types.py:87` half_width formula bounds: `half_width = 1/√(n+1)`
  ranges `(0, 1]`; `mean` is bounded within `(-1, 1)` for any real assertion mix. A
  `DimensionRuling`'s continuous fields need matching bounds (`mean` clamped to
  `[-1, 1]`, `half_width` to `(0, 1]`) to stay in the range the Scorer's sampling code
  already assumes elsewhere (`_sample_dimension`, `_map_to_range`) — no clamping exists
  today because no caller has produced an out-of-range pin yet.
- **F39** — `src/screen/web/templates/rating.html:9-11` — the dimension-group header
  (`<h3 class="dimension-title">` + digest paragraph) is the natural attachment point
  for a `DimensionRuling` control: it already sits above the per-assertion list, at
  dimension granularity, not assertion granularity.
- **F40** — review-ux/scouting.md F22, F23 — server-rendered HTMX stays the delivery
  shape; client-side-only rich interactions (drag, canvas planes) are explicitly out of
  scope. A continuous 2-axis input therefore can't be the prototype's JS canvas plane
  (`job-screener-prototype/templates/review.html:56-119`, confirmed by direct read: a
  `<div id="plane">` with a JS click handler computing x/y from `getBoundingClientRect`)
  — that pattern is prototype UX not carried forward (per W4) and depends on
  client-side JS this bearing doesn't want. Two native `<input type="range">` elements
  (fit, settledness) posted via a form is the shape consistent with F22/F23 and with
  the existing fit-segment buttons' plain-HTML-form pattern (`rating.html:19-30`).
- **F41** — `src/screen/store/migrations/0002-0004*.sql` — the existing migration
  pattern for a new sibling ruling type is one additive file: a table keyed on the
  relevant id(s), an upsert-by-key repo function (`upsert_assertion_ruling`,
  `repo.py:69-79`, unique index from migration 0003), and paired
  `mappers.py` to/from functions. A `dimension_rulings` table follows the same shape,
  keyed `(opening_id, target)` unique, since a dimension-level ruling is per-opening
  (unlike `assertion_rulings`, which needs no `opening_id` column because it's reached
  through `assertion_id`'s own foreign key — F25/F28's repo comment, `repo.py:82-85`).
- **F42** [x] — review-ux/scouting.md F27 — closed already: no snap-to-bucket, continuous
  pin feeds mean/half_width directly. Carried forward unchanged; this scouting pass adds
  no new information on the *interaction* shape, only on where it slots into existing
  code (F35-F41).
- **F43** [x] — operator: the y-axis reads as *how strongly I feel*, not as spread
  directly — 0 is "I have an opinion, but it's loose"; the top is maximum conviction,
  and even there some spread remains (never a point estimate) → bearing Approach.
  `half_width` therefore falls as the slider (`settledness`) rises, floored above zero
  at the top rather than hitting it: `half_width = hw_max - settledness * (hw_max -
  hw_min)`, with `hw_max`/`hw_min` both configured, `hw_min > 0` enforced. Matches
  domain-model.md §Ruling/decisions E3: the operator may be noisy; the system may not
  manufacture false precision even at maximum stated confidence.
- **F45** — decisions loader pattern (`scoring.yaml`'s `provenance_weight`,
  `src/screen/score/loader.py:52-56`) — unmeasured numeric dials already live in
  `scoring.yaml`, not hardcoded, per the house rule (AGENTS.md: "a named config value
  the operator owns, not a constant hidden in code"). `hw_max`/`hw_min` (F43) belong
  there, alongside `bands`/`provenance_weight`, not as literals in `scorer.py` or
  `types.py`.
- **F46** — operator — pins are not revertable: no delete/unset control. Resubmission
  still replaces the prior value (upsert-by-`(opening_id, target)`, same as
  `AssertionRuling`'s re-rating pattern, review-ux/scouting F26) — "not revertable"
  means no path back to *unpinned*, not that the value is frozen once set.
- **F44** [ ] — does submitting a `DimensionRuling` invalidate/replace the cached
  `DimensionDigest` for that target, or are they unrelated (digest describes the
  evidence, ruling describes the operator's placement — no shared staleness key today)?
  `digest_for_target`'s staleness key is assertion count only (`service.py:38-53`); a
  `DimensionRuling` doesn't add an assertion, so the existing cache wouldn't be touched
  either way — flagging as a finding, not a defect, since nothing requires them to
  interact.

## Not Yet Settled

- **F44** — confirmed no interaction required with `DimensionDigest` caching; noted so a
  future reader doesn't go looking for one.
- Whether the queue-applies-rulings gap (named in `docs/CURRENT.md`'s prior entry, now
  superseded) should be picked up in the same bearing or stays a separate thread — not
  re-scouted here since the operator retargeted `CURRENT.md` away from it; flag only if
  raised again.
