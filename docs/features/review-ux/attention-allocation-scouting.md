---
feature: review-ux
type: scouting
date: 2026-09-01
commit: ef18efc
parent: ./scouting.md
---

## What We're Doing

Operator's framing, this session: the actual goal is optimizing *time budget* — get a job
that fits the rubric as closely as possible with the least time invested. This implies
explore/exploit, and which opportunities are worth investing time in (apply) versus
triaging out is deliberately **dynamic**, driven by backlog volume, automation capacity, and
the operator's own daily/weekly strategy — not a fixed categorical taxonomy decided in
advance. The operator wants **signals**, not buckets: enough surfaced information to compose
their own strategy per session, not the system pre-deciding "this is an apply, this is a
research, this is a discard."

Two further corrections mid-session:

1. Initial framing wrongly folded "which opening to focus research/attention on next" into
   approach-EV (open-questions #5). Operator caught this: #5 is about modeling
   cost/value of *approach actions* (cover letter vs. intro call) against real outcome data
   — genuinely blocked on data that doesn't exist yet. Ranking openings by how much their
   *own standing could still move* needs no outcome data; it's the same VOI math
   `rating-voi-triage` already uses, one level up.
2. The operator wants **two separate but related bandits**, not one: (a) the agent
   continuing/extending a research pass on an opening, and (b) the operator making
   decisions (assertion/dimension rulings) on an opening. Different actors, different action
   costs, same underlying leverage signal (how much would resolving this move standing).

## Findings

- **F1** — decisions.md W3 (`adopted`, from O5) — VOI is already defined: "would this
  change what happens," not "how far does standing move" in absolute terms. Established for
  *research targeting*; `rating-voi-triage` is its sibling for *rating tasks within one
  opening*. Neither existing instance ranks *openings* against each other.
- **F2** — `src/screen/score/triage.py` (`rating_task_candidates`, `_swing`) — the exact
  mechanism for opening-level VOI already exists at the wrong granularity: `_swing` computes
  `|standing(best-case override) - standing(worst-case override)|` for one unrated
  assertion/dimension target, holding everything else fixed, using a shared seed so ranking
  isn't sampling noise (guards against S6's corollary). Generalizing this to "how much could
  this *opening's* standing move if its highest-leverage unresolved target were resolved" is
  a straightforward reuse — sum or max of per-target swings already computed per opening, no
  new scoring primitive.
- **F3** — `src/screen/score/scorer.py` (`resolve_favourably`, `unexamined_targets`) — the
  reach counterfactual already isolates *which targets are unexamined* per opening. This is
  half of the "which opening is most worth a research pass" signal: an opening with several
  high-weight unexamined targets and wide reach-standing gap is a better research bet than
  one that's already saturated.
- **F4** ⚠ — this session's read of `data/live/screen.db` (Wheel example, see conversation)
  — `resolve_favourably`/`unexamined_targets` only detect **fully blank** targets (zero
  counted assertions). A target with one weak `model_proposed` assertion and a
  low-settledness `DimensionRuling` (e.g., `peer` at `settledness=0.33`) reads as "examined"
  and contributes nothing to `reach`, even though real research/rating leverage remains
  there. Any opening-level research-VOI signal built on `unexamined_targets` alone will
  **undercount** research value on partially-explored openings — it needs to reason about
  `half_width`/`settledness`, not just presence/absence of assertions. This is a gap in
  today's mechanism, not a bug — `resolve_favourably` was built for the reach counterfactual
  (S5), not as a general leverage detector.
- **F5** — `src/screen/score/scorer.py:41-52` (`TargetStats`) — `n`, `mean`, `half_width`
  are already computed per target per opening; `half_width` directly measures "how much
  could this target's contribution still move" independent of whether it's technically
  "unexamined." This is the more general leverage primitive F4 says is missing from
  `resolve_favourably` — a wide half_width on a high-weight target is high leverage whether
  or not any assertion exists yet.
- **F6** — decisions.md S2/D7 (review-ux/scouting F13/F50, measured on the one real pass) —
  constraints, not dimensions, did the discriminating (302× standing lift, two constraint
  labels contributing 126×). Any cross-opening or cross-target leverage ranking should
  surface constraint targets as high-leverage by default, consistent with the existing
  rating-VOI weighting note.
- **F7** — domain-model.md §Workflow — `ResearchQueue` ("proposed research targets ranked by
  VOI... operator batch-authorizes... stopping rule: when no affordable research would
  change anything") is named in the domain model but has **zero implementation** (`grep
  ResearchQueue src/` returns nothing). This is the natural home for "agent bandit: which
  opening's research pass is worth running next" — a queue-level ranking, not a new concept,
  just an unbuilt one.
- **F8** — `rating-voi-triage.md` Approach — "arm = opening, task = one unrated
  assertion/dimension-target." That mechanism's *task-level* ranking already exists; what's
  missing is the *arm-level* (opening) ranking that would let the operator or the agent pick
  which opening to spend the next unit of attention on, across the whole backlog rather than
  within one already-chosen opening.
- **F9** — `rating-voi-triage.md` Not Doing — "Cross-opening explore/exploit sequencing...
  is a smaller, separate concern not blocked by this one." Direct precedent: this feature
  was explicitly scoped to defer exactly what this scout now picks up, and named it as
  tractable ("smaller"), not blocked.
- **F10** — operator, this session — explicitly rejects baking in a fixed three-bucket
  taxonomy (apply/research/discard) as the deliverable. The ask is signals (standing, reach
  gap, ceiling gap, unreachable, per-opening swing/leverage for each bandit) that the
  operator composes into their own daily/weekly strategy — volume-driven, automation-driven,
  mood-driven. Nothing here should decide "act" on the operator's behalf (consistent with
  domain-model.md's Inbox principle: routing, not deciding).
- **F11** — operator, this session — two bandits, not one: **(a) research-pass bandit** —
  which opening should the agent spend its next research pass on (arm = opening, action =
  extend/continue existing research); **(b) rating bandit** — which opening should the
  operator spend their next few rating minutes on (arm = opening, action = assertion/
  dimension rulings). Related (same underlying per-opening leverage signal) but distinct
  action spaces, distinct actors, likely distinct costs.
- **F12** — `standing-reach-lenses.md` (separate thread) — the queue's single standing-
  sorted list and relative sparkline scaling are being reconsidered there as separate
  standing/reach lenses (apply vs. research views). This is adjacent but not identical to the
  two bandits: the lens thread owns the display/sort shape, while this thread owns the VOI/
  leverage computation that would feed a research lens. Both should share the same
  underlying signal so the operator isn't reading two different "research opportunity"
  numbers.
- **F12** — `src/screen/intake/transcript_io.py` (review-ux/scouting F8, F9, F11) — research
  state is meant to be computed from the replayable transcript, not stored separately. A
  research-pass bandit's "has this opening already had N passes / hit its search budget"
  input should read the transcript the same way, not add new persisted counters. F11 (this
  scout's own numbering restarts per-file per the scouting convention) in
  `review-ux/scouting.md` already flags this is unverified for a pass that actually exhausted
  search budget — the research-pass bandit inherits that same unverified dependency.
- **F13** [ ] — is "how much would a research pass move this opening" computed the same way
  as `resolve_favourably`'s reach counterfactual (one hypothetical Strong pass per
  currently-blank target), or does it need a version that's sensitive to *existing* thin
  evidence (F4's gap) to correctly rank partially-researched openings? If the former, it's
  a two-line reuse; if the latter, it needs a new counterfactual shape.
- **F14** [ ] — for the rating bandit, is "opening-level swing" a straight reuse of summing
  `rating_task_candidates`' per-task swings for that opening (cheap, already computed), or
  does the operator want it to account for the total number of open tasks too (an opening
  with five wide gaps might deserve more attention than one with one narrow gap, even if
  the top single-task swings are similar)?
- **F15** [ ] — where does this live for display? The queue is currently one list sorted by
  `standing`. Do the new leverage signals become additional columns/values on the existing
  queue rows (operator reads them and decides), a separate ranked view analogous to a real
  `ResearchQueue`, or both? F10's "no baked-in buckets" suggests signals-on-the-existing-queue
  over a new prescriptive view, but this isn't settled.
- **F16** — review-ux/scouting.md F14 (decisions E2) — any new leverage/swing number is
  display-only and derived, same constraint `rating-voi-scouting.md` F49 already established
  for within-opening swing — must not feed back into `Assertion`/`DimensionRuling` or the
  Scorer itself.

## Not Yet Settled

- F13 — whether the research-pass bandit's leverage signal needs a half-width/settledness-
  aware counterfactual (new mechanism) or can reuse `resolve_favourably` as-is (existing
  mechanism, understates partially-researched openings per F4).
- F14 — single-task-swing vs. aggregate-open-tasks for the rating bandit's opening-level
  score.
- F15 — display shape: signals bolted onto the existing queue vs. a new ranked view (the
  never-built `ResearchQueue` from the domain model, F7) vs. both.
- Whether one shared "opening leverage" number serves both bandits, or whether the
  research-pass bandit and rating bandit genuinely need separate leverage computations given
  F4's gap only affects the research side (an operator rating can resolve thin evidence
  directly; a research pass can't distinguish "thin" from "blank" today).
