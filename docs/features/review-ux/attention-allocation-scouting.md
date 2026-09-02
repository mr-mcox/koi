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
- **F13** [x] — is "how much would a research pass move this opening" computed the same way
  as `resolve_favourably`'s reach counterfactual (one hypothetical Strong pass per
  currently-blank target), or does it need a version that's sensitive to *existing* thin
  evidence (F4's gap) to correctly rank partially-researched openings? Closed by F19: the
  coarse contested/not-contested filter needs neither — reuses `reach` vs. boundary as-is.
  F4's gap survives only as a second-order tiebreak inside the contested set.
- **F14** [x] — for the rating bandit, is "opening-level swing" a straight reuse of summing
  `rating_task_candidates`' per-task swings for that opening (cheap, already computed), or
  does the operator want it to account for the total number of open tasks too (an opening
  with five wide gaps might deserve more attention than one with one narrow gap, even if
  the top single-task swings are similar)? Closed by F20: neither — reframed as
  distance-to-boundary, not a swing aggregate.
- **F15** [x] — where does this live for display? The queue is currently one list sorted by
  `standing`. Closed by F27/F28/F29: neither a bolted-on signal on the existing row nor a
  separate multi-lens view — one additional derived column (boundary-crossing
  probability) on the single existing queue, replacing the earlier three-lens direction.
- **F16** — review-ux/scouting.md F14 (decisions E2) — any new leverage/swing number is
  display-only and derived, same constraint `rating-voi-scouting.md` F49 already established
  for within-opening swing — must not feed back into `Assertion`/`DimensionRuling` or the
  Scorer itself.
- **F17** — operator, this session — the actual product goal, reframed: apply to the
  top-K (K≈10, configured, likely to grow) each week; openings fall out of the
  competitive set once applied-to (pipeline stage, domain-model.md §Opening), and an
  affordance discovered later (e.g. a warm intro) can bump one back up. This is **fixed-
  budget top-K identification** (successive-accept-reject / racing-algorithm shape), not
  cumulative-regret bandit optimization — a different objective than "how much could this
  arm's own value move," which is what `_swing`/`rating_task_candidates` (F2) and the reach
  counterfactual (F3) currently compute. W3's VOI distinction ("would this change what
  happens," not "how far does standing move," F1) already drew this line for research
  targeting; F13/F14 as written were generalizing the wrong half of that distinction across
  openings.
- **F18** — `src/screen/score/scorer.py:41-52,80-89` (`TargetStats`, `ScoreResult.p_stderr`)
  + domain-model.md Scorer section ("reach never sorts... standing is the only sort key") —
  the boundary-relative primitive this reframe needs is mostly built, not new: `standing`
  and `reach` are already computed per opening. Let *boundary* = the standing of whichever
  opening currently sits at rank K. An opening whose `reach` doesn't clear the boundary
  cannot enter the top-K regardless of research/rating spent — deprioritize for both
  bandits. An opening whose `standing` already clears the boundary by several `p_stderr`s
  (F55, rating-voi-scouting.md) is a stable member, not a research target (though still a
  candidate for the rating bandit if tighter confidence is wanted before committing to
  apply). The **contested set** — `reach ≥ boundary` and `standing` within noise of it — is
  where both bandits' budget should go. No new Scorer primitive; the missing piece is
  comparing each opening's (standing, reach) bracket against the K-th competitor's
  standing, computed at the queue/route layer the same way F16 already constrains any new
  signal to be.
- **F19** — this reframe answers F13's question directly: the coarse "is this opening even
  contested" filter (F18) needs no half-width/settledness-aware counterfactual — `reach`
  vs. boundary settles it with existing machinery, cheaper than either option F13 posed.
  F4's gap (blank vs. thin evidence) still matters, but only as a *second-order* question
  inside the contested set — which target within a contested opening to spend the next
  research unit on — not a queue-wide ranking mechanism. F13 → closed, narrowed scope.
- **F20** — this reframe dissolves F14 in its original form (sum-of-swings vs.
  count-aware-sum). The boundary-relative question isn't "how much could this opening's
  score move" at all; it's "how likely is this opening to cross the boundary." The rating
  bandit's opening-level ranking should be distance-to-boundary in `p_stderr` units (or
  count of contested targets whose resolution could plausibly cross it), not raw swing
  sum or task count. F14 → closed, reframed as a boundary-distance metric.
- **F21** — this reframe reopens F15 with a directional answer: "contested near the
  cutoff" is a materially different lens than "sorted by standing," and F10's "no baked-in
  buckets" objection doesn't apply here — this isn't a categorical bucket (apply/research/
  discard), it's a continuous distance-to-boundary signal the operator still reads and acts
  on themselves. Argues for the never-built `ResearchQueue` (F7) as a genuinely separate
  view, not signals bolted onto the existing queue row.
- **F22** — domain-model.md §Opening ("Pipeline stage: `screening → handed-off → applied →
  closed(outcome)`") — the boundary/top-K set is naturally scoped to openings still in
  `screening`/`handed-off`; `applied` and `closed` openings exit the competitive set by
  construction (they've already consumed the action this whole mechanism is optimizing
  toward), matching the operator's "fall out as I apply" framing exactly. No schema change
  needed — the stage field already exists in the domain model (though per F22's sibling
  finding below, isn't yet implemented in code).
- **F23** ⚠ — `grep -rn "pipeline\|stage" src/screen/types.py` (this session) — returns
  nothing. `Opening`'s pipeline-stage field described in domain-model.md §Opening is **not
  implemented** — `screen.types.Opening` has no stage attribute today. The top-K/boundary
  view (F18, F22) needs *some* notion of "still competing vs. already applied" to exclude
  applied openings from the contested set; this is a real gap, not a display nuance, and
  likely a small prerequisite slice before the boundary view can be built correctly.
- **F24** — operator, this session — an affordance discovered after the fact (e.g. a
  second-degree contact enabling a warm intro) can bump an opening back into contention.
  domain-model.md §Opening already names affordances as "collected data, never
  directives" and open-questions.md #5 already parks any EV-weighting of them ("approach-
  EV") as blocked on real outcome data that doesn't exist yet. This reframe doesn't need
  approach-EV solved: an affordance is a new/changed assertion like any other (non-scoring
  target or otherwise) that can change an opening's `standing`/`reach` bracket relative to
  the boundary through the existing scoring path — no new mechanism, consistent with F16's
  constraint that nothing here is a new blended field.
- **F25** — operator, this session — asks whether research-bandit and rating-bandit
  leverage are "easily distinguishable." F18's boundary-distance metric is actor-agnostic
  (a property of the opening's current bracket vs. the boundary); what distinguishes the
  two bandits is the **action**, not the leverage signal — same distinction F11 already
  drew ("related... but distinct action spaces, distinct actors, likely distinct costs").
  The research bandit answers "which contested opening should the next research pass
  target" (narrows the bracket via new evidence, F19); the rating bandit answers "which
  contested opening should the next few operator-minutes target" (narrows the bracket via
  ratification, reusing F2's existing per-target swing *within* the contested set only).
  Both consume the same boundary computation (F18); only the candidate-generation step
  differs. Operator also flagged research is currently cheaper per unit and will be run
  first, with correlation-to-rulings work (precedent matching, F-references in
  rating-voi-scouting.md) as future work to make it more reliable — this is a sequencing/
  cost note for Approach, not a new leverage computation.
- **F26** — operator, this session — the existing `focus`/"Start focused ratings session"
  entry point (`src/screen/web/routes.py:230-255`, `_focus_queue_items`/`_opening_leverage`/
  `focus_session`) may be the wrong mechanism entirely and should be considered for
  removal. It currently orders openings by raw summed swing (F2's per-opening reuse, not
  boundary-aware) — exactly the cumulative-regret framing F17 says is the wrong objective
  for this goal. Whether it's replaced by the new boundary-scoped view (F21) or removed
  outright is a bearing-time decision, not resolved here.

- **F27** [x] — closed by F19/F20/F21, superseded by F29-F31 below. F15 itself is now
  closed: not bolted onto the existing queue row (operator, this session, explicitly
  rejects that), and not the three-lens plan either (§F28) — one queue, one new derived
  column.
- **F28** [x] — operator, this session — going into this conversation the operator was
  leaning toward **three entry-point views** (`sort-and-presentation-scouting.md`,
  `standing-reach-lenses.md`: guided-triage / sorted-by-standing / sorted-by-reach).
  Explicitly reconsidered and superseded this session: raw `reach` was already barred from
  sorting (S5/wall 7, `standing-reach-lenses.md` F4) precisely because it saturates, so a
  "sorted by reach" lens was never going to be honest on its own; a third guided-triage
  view duplicates whatever the boundary metric already shows. F17's reframe replaces all
  three candidate lenses with one additional column on the existing single queue.
- **F29** [x] — operator, this session — the wanted display is `standing` (unchanged,
  existing sort key) plus a second column: **P(this opening crosses the top-K boundary)** —
  the probability it enters or leaves the top-K set, not a swing/leverage magnitude. This
  is a sharper version of F18's contested-set filter: instead of a boolean
  contested/not-contested split, it's the probability itself, read directly off the same
  Monte Carlo trace already computed for `standing` — `P(sample rank crosses K)` needs no
  new sampling machinery, only comparing each opening's trace against the K-th opening's
  trace (or a resampled joint comparison) instead of a single scalar threshold. Supersedes
  F18's simpler reach-vs-boundary boolean as the target display metric, though F18's cheap
  reach-vs-boundary check may still serve as a pre-filter to avoid this heavier comparison
  for openings nowhere near contention.
- **F30** [x] — operator, this session — explicit instruction: **no false precision at the
  boundary is being chased here** — best-effort is fine, and keeping code/latency
  complexity down outranks a more exact boundary-crossing estimate. This directly bounds
  F29's implementation: a full joint resampling comparison across all pairs is not
  required if a cheaper approximation (e.g., comparing each opening's trace to the single
  K-th-place trace, or a normal approximation from `standing`/`p_stderr`) gets a usable
  answer — consistent with domain-model.md wall 4 ("precision ranks; displays avoid false
  precision") but framed here as an implementation-cost bound, not just a display-honesty
  one.
- **F31** — operator, this session — the boundary-crossing probability is explicitly the
  budget-allocation instrument: read low P(crossing) as "stable, spend no more time here"
  and high P(crossing) as "more rating/research time here could change whether I apply,"
  across *both* bandits (research and rating) and also informs "apply to top L now with
  current budget" as a direct policy read of the same number — no separate signal needed
  for that framing.
- **F32** — operator, this session — pipeline-stage modeling (F22/F23) is explicitly
  deferred: "assume they are all the same lifecycle stage" for now. F23's implementation
  gap stands as a named future dependency, not a prerequisite slice for this feature — the
  boundary/top-K computation can run over the full backlog unconditionally until stage
  modeling is separately built.
- **F33** [x] — this session — closes F29/F30 by selecting the **K-th-place trace
  comparison** as the cheap approximation: compare each opening's Monte Carlo trace
  elementwise against the trace of the opening currently at rank K, using the shared
  `config.seed` already shared across all `score()` calls (domain-model.md Scorer section,
  `scoring.yaml:17` `seed: 20260821`). `P(rank crosses K)` is estimated as the fraction of
  samples where this opening's overall draw exceeds the K-th-place opening's overall draw.
  Uses the existing traces directly, no additional sampling, deterministic given the shared
  seed — a route/display-layer computation, consistent with F16, no new Scorer primitive.
  Known tradeoff: treats the K-th-place opening as a fixed reference; misrepresents only
  when multiple openings are simultaneously contesting the boundary in a way that would
  itself change who holds rank K — the recalibration trigger, not a blocker to starting.
- **F34** [x] — operator, this session — settles F25: the operator's workflow is a single
  repeated **review session** (not modeled as a persisted object) with a fixed sequence:
  1. intake new opportunities; 2. run the research bandit with a configured budget;
  3. run the rulings bandit (operator acts); 4. decide whether to return to step 2 or 3,
  or stop and apply to the top L from current standing. This is a **sequencing heuristic**,
  not a modeled state machine — it settles F25 by establishing that the two bandits are not
  interleaved opportunistically per-opening, but batched: research runs before operator
  attention, matching the operator's intuition that research is cheaper/higher-volume and
  rulings are best spent on openings that have already had a research pass. The
  boundary-crossing column (F33) is the shared input both steps 2 and 3 read from within a
  session. The return-or-stop decision at step 4 stays entirely operator-driven — no
  system-generated "stop now" directive. The exact research budget (X) and apply threshold
  (L) remain configured numbers (scoring.yaml precedent, AGENTS.md "measure before model"),
  not fixed by this finding.

## Not Yet Settled

- F34's sequencing heuristic (research always precedes rating within a session) is an
  untested assumption — recalibrate if a real session shows the operator wanting to rate
  an opening *before* its research pass completes (e.g., an obvious disqualifying
  constraint rated in seconds, cheaper than waiting on research), which would argue for
  interleaving rather than strict batching.
- F33's fixed-K-th-reference approximation is a recalibration candidate, not a settled
  mechanism: if real queue data shows several openings simultaneously contesting rank K
  (the identity of "the K-th opening" itself churns turn to turn), the fixed-reference
  comparison may need to become a pairwise or resampled comparison after all — deferred
  until that's observed, per F30's cost bound.