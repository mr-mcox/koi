---
feature: review-ux
type: scouting
date: 2026-08-31
commit: 10eda09
parent: ./scouting.md
---

## What We're Doing

`docs/CURRENT.md` names the tip: "Rating-VOI / triage (review-ux/scouting F3, F31,
dimension-ruling.md's Not Doing) — no bearing yet." The operator's live framing, this
session: ratings have gone from pets (a handful of exciting one-offs) to cattle (10+ new
candidates just from the last few days, across two job boards plus recruiter inbound).
The ask is a UX that directs attention to a few things across a few different areas at
once, explore/exploit with the operator as the bandit, and a **cost to switching** so
attention lands as a few tasks per opportunity before moving on — spent on the
highest-leverage information, not spread thin.

## Findings

- **F47** — operator (this session) — the concrete mechanism requested: surface a small
  number of opportunities at a time, drawn from different "areas"; a switching cost so
  the operator does several rating tasks (assertion and/or dimension rulings) per
  opportunity before moving to the next; selection driven by highest-leverage
  information, explicitly framed as explore/exploit.
- **F48** — decisions.md W3 (`adopted`, from O5) — VOI is already defined, for research:
  "would this change what happens," not "how far does standing move." review-ux/scouting
  F3 names this feature's central idea as the rating-side sibling of that same principle —
  not a new principle to invent.
- **F49** — review-ux/scouting.md F14 — any leverage/VOI number shown to the operator is
  **display-only, derived, and must never feed the Scorer** — reopening confidence-as-
  multiplier (rejected three times, decisions.md S8) is the specific failure mode a
  "leverage score" risks if it blends into `Assertion`/`DimensionRuling` fields instead of
  living in the route/template layer.
- **F50** — review-ux/scouting.md F13, decisions.md S2/D7 — measured on the one real
  pass: constraints, not dimensions, did the discriminating (302× standing lift, 126× from
  two constraint labels vs. 2.4× from nine dimension entries). Any rating-VOI weighting
  should treat constraint targets as higher-leverage by default, not weight-equal with
  dimensions.
- **F51** — `docs/features/review-ux/dimension-ruling.md` Not Doing — "Rating-VOI / triage
  — this bearing is the last precondition, not the triage mechanism itself." Confirms
  `DimensionRuling` (now `done`) was explicitly the precondition for this exact tip, not a
  separate thread.
- **F52** — domain-model.md §Workflow — `ResearchQueue` is the only VOI-ranked,
  batch-authorized queue that exists today, and it ranks *research* targets, not *rating*
  tasks. No `RatingQueue` / attention-allocation concept exists in the domain model yet —
  this feature is new workflow-context territory, not an extension of an existing queue
  type.
- **F53** — `data/live/screen.db` (live corpus, read this session) — 5 companies, 5
  openings, 52 assertions, 14 `assertion_rulings`, 3 `dimension_rulings`. Small-n corpus:
  echoes learnings.md Q3's resolution ("measure before model" — costs/weights should be
  configured numbers the operator owns, not fit parameters, until there's a real corpus to
  fit against).
- **F54** — `src/screen/score/scorer.py:96-104` (`_stats_for_target`) — the exact seam a
  VOI signal would read already exists: `_target_stats`/`_TargetStats` (mean, half_width,
  `n`) is computed per target today for scoring; a per-target "how much would one more
  rating move things" signal is a function of this same shrinkage math (wide half_width +
  high dimension weight/constraint leverage = high potential movement), not a new data
  model.
- **F55** ⚠ — `src/screen/score/types.py:87-92` (`ScoreResult.p_stderr`) — decisions.md's
  S6 corollary: "in the doldrums, standing is estimated from a handful of hits — two
  results can differ by less than this and the ordering, while reproducible, is not a real
  one." A VOI/triage ranking built on raw `standing`/`half_width` differences between
  openings risks ranking Monte Carlo sampling noise as signal exactly where the corpus is
  thinnest (5 openings, most barely rated) — the mechanism needs to be noise-aware, not a
  bare sort on point differences.
- **F56** [x] — the operator's "10+ opportunities... just through two job boards and
  recruiters reaching out" are not yet `Opening` rows — they haven't been intake'd or
  research-passed. Does this feature's triage operate on **already-researched openings
  choosing their next rating task** (the `DimensionRuling`-adjacent, dimension-ruling.md
  "last precondition" reading), or does it also cover **which of the 10+ leads deserve
  intake at all** (open-questions.md #10, "lightweight vs. heavy screening at intake" —
  explicitly a separate, deliberately-deferred question)? The request's framing spans
  both; `docs/CURRENT.md`'s pointer and dimension-ruling.md's Not Doing both name the
  former specifically. Closed — operator: scope is already-intake'd openings only;
  intake is cheap, so pre-intake backlog triage is not this feature's concern → bearing
  Problem.
- **F57** [x] — what are the "few different areas" the explore/exploit selection draws
  from — openings (today: 5), companies, or rubric dimension groups within one opening?
  The bandit's "arms" need a concrete referent before a mechanism can be designed.
  Closed — operator: the arm is the **opening** → bearing Approach.
- **F58** [x] — is "switching cost" a **configured number** feeding a scoring/ranking
  formula (matching domain-model.md §Workflow: "Costs are configured numbers the operator
  assigns" — no duration tracking, per W3/learnings Q3), or a **UI/session mechanic**
  (e.g., the surface literally won't let you move to a new opportunity until N tasks are
  done on the current one)? These are different builds — one is a ranking-formula
  parameter, the other is an interaction constraint. Closed — operator: per-opening a
  **task budget** (3-4 unrated assertion/dimension-ruling tasks), chosen as the set that
  collectively moves that opening's score the most among everything unrated on it → bearing
  Approach.
- **F59** — review-ux/scouting.md F17 — `Target` is a closed Literal (Wall 3); any new
  triage/leverage concept must be additive (a computed display value or a new sibling
  type) and cannot loosen `Target`/`Assertion`'s existing shape.
- **F60** — operator (this session) — the existing `rate` page's layout is decent as a
  base, but the ask is a **focused task view**: given the chosen budget of unrated items
  for one opening, render only those tasks (with enough surrounding context to rate them —
  digest, citations) and hide the rest of the assertion/dimension list, rather than
  showing the full rating page with everything visible.
- **F61** — `src/screen/web/routes.py:63-113` (`_dimension_groups`, `_rating_context`) —
  both already compute, per opening, the full set of dimension groups each carrying its
  assertions and any existing rulings. The unrated-item set for a budget (F58) is a filter
  over exactly this structure (assertions with no entry in `_latest_ruling_by_assertion`,
  dimension groups with `ruling is None`) — no new read path needed to identify candidates,
  only a new selection/ranking step over already-assembled context.
- **F62** [ ] — how does "collectively moves the score the most" get computed for a
  *candidate set* of 3-4 items, given the Scorer only takes a single fixed
  `rulings`/`dimension_rulings` mapping per `score()` call (scorer.py `score()` signature)?
  A per-item marginal-movement estimate (e.g., resolve each unrated item to its target's
  current shrunk mean, or to the reach-favourable hypothetical, and measure standing
  delta) is a plausible cheap proxy, but "collectively" implies some combination logic
  (sum of marginals? re-score with all N pinned to their means at once?) that no finding
  yet settles — and F55's noise-floor warning applies directly to whatever comparison is
  used.
- **F63** — review-ux/scouting.md F20 — the load-bearing UX bar already established:
  submitting a rating re-sorts/updates without a full page reload (HTMX partial swap). A
  focused-task view's per-task submission should follow the same pattern, not introduce a
  new interaction contract.
- **F64** — operator (this session) — confirmed: "which opening to focus on next" needs
  no mechanism — intake is cheap, so the next opening is just "grab a URL and intake it."
  The 10+ figure was volume context (cover letters/applications/warm-path effort must
  concentrate on the most promising openings as volume grows), not a request for
  cross-opening ranking — that consumer (approach-EV / obtainability) is downstream of
  standing/reach and explicitly deferred (open-questions.md #5). Closes the Not Doing
  scope-check from the prior bearing draft with no changes needed.

## Not Yet Settled
- F62 — the exact per-item leverage proxy and how per-item estimates combine into a
  "collectively moves the most" set — a bearing/implementation-time numeric choice, not
  yet pinned to one formula.
- Whether this reuses `rating.html` (a filtered mode) or is a distinct new template, per
  review-ux/scouting F19 ("the queue is the central view but not the only one") —
  F60/F61 suggest a filtered mode of the existing rating context, but this is an
  implementation-shape call, not yet decided.
