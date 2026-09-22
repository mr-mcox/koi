---
name: durable-decisions
type: decision-record
date: 2026-08-21
provenance: distilled from prototype hand-off conversation; no committed codebase at writing
companions: prototype-decisions.md, domain-model.md
---
# Durable Decisions — Clean Build Seed
Distilled 2026-08-21 from the prototype's decision record. Only decisions that survive the
prototype are here; prototype-mechanics decisions (which web framework, which sample count)
are deliberately dropped. The rejected alternatives are the most valuable part — several
were killed by numeric demonstration, and the demonstrations are what stop the clean build
re-deriving them.

**Status tags:**
- `demonstrated` — settled by a numeric demonstration or repeated rejection; reopening
  requires new evidence, not new taste.
- `adopted` — decided during handoff distillation; the steel thread exists to test these.
- `provisional` — held deliberately loosely; a named volatility area.

D-numbers cite `prototype-decisions.md`, which keeps the full reasoning and defines the
Company A–D pseudonyms.

---

## Scoring core

### S1 · Companies are distributions; the queue sorts on P(value > bar) · `demonstrated` (D6) · superseded by S9

Four required properties: convergence at full coverage; an incentive to keep collecting
when evidence is thin; honesty about what isn't known; a sort favoring a wide-open unknown
over well-established mediocrity. **No point estimate satisfies all four.** Worked check:
mediocre-fully-researched has the higher mean (0.50 vs 0.47) and far lower P (4% vs 31%)
than strong-but-hybrid — sorting on the mean buries the case worth one email.

**Rejected:** point estimates; confidence-as-multiplier (three separate times — D2);
unknowns-as-zero with fixed denominator (mathematically `score × coverage`, makes
unresearched companies sort low — backwards).

### S2 · Constraints are discount factors, not gates and not weights · `demonstrated` (D7) · superseded by S12

Location, internal culture, extractive business: each a tolerability factor in [0, 1] with
its own uncertainty, multiplied against quality. Negotiability is **variance**, not a lower
value. **Why not "weight it heavily": measured — to drag a perfect company below neutral,
location must outweigh all seven dimensions combined (≥ 14 of 28), past which location *is*
the score.** No weight means "usually matters, occasionally decisive."

Constraints are allowed to be fatal at the current bar (D18: lots of fish in the sea); the
remedy if the backlog empties is lowering `bar`, not redesigning the constraint.

**Rejected:** pass/fail gates (three rewrites); heavy additive weights (the measurement).

### S3 · Unexamined enters wide at the prior; "no signal" is the outcome of looking · `demonstrated` (D5, D19)

An unexamined target is a wide distribution, never excluded, never defaulted clean.
Confirmed-mixed is narrow-at-zero; unexamined is wide-at-zero — sharper than exclusion ever
was. `no_signal` is a label research *earns*; under the opposite default the single most
valuable research action on the prototype's best company would have been worth nothing.
Measured consequence, accepted: every P drops ~an order of magnitude; ordering unchanged.

### S4 · Unreachability is analytic, not sampled · `demonstrated` (D20) · superseded by S9

The queue splits live / over-the-cliff. Over the cliff = the closed-form ceiling (everything
at the top of its support) is at or below the bar. "No sample cleared" and "no sample
*could*" are different claims; only the second justifies demotion. Nothing is deleted.

### S5 · The queue reads a standing/reach pair; reach never sorts · `demonstrated` (D21) · superseded by S9

`standing` = P(> bar) now, the only sort key. `reach` = P(> bar) after one good pass on
every unexamined target; it describes the remaining upside and collapses to standing at full coverage. **Reach saturates — an empty
record (0.971) out-reaches a researched good company (0.721) — honest as a statement,
nonsense as an ordering.** Rejected, all measured: pessimistic twin (all zeros), q50 bands
(conflates bad with unknown), ceiling bands (no resolution), rank-relative bands (fake
precision).

### S6 · Precision ranks; bands display · `demonstrated` (D10)

Distributions drive ranking. The UI shows sparklines and coarse probability, never decimals — a
single aggregator review must not produce "6.7/10." Corollary from real use: "wide because
negotiable" and "wide because unexamined" must never share a display label.

### S7 · The rollup is mechanical; the model never renders verdicts · `demonstrated` (D4)

Dimension score is a deterministic aggregate over assertions. The model gathers and labels
evidence; scoring is auditable arithmetic. (The averaging form itself will change with S8 —
what's durable is *mechanical and auditable*, not the specific formula.)

### S8 · Provenance sets variance · `adopted` — steel-thread this first

An assertion is a noisy measurement of what the operator would conclude. The noise comes
from who judged it: unexamined (maximal) → model-proposed → precedent-matched → ratified
(narrowest, **not zero** — the operator is noisy too). This amends the letter of D2
(Medium/High treated identically — a rung-less ladder the plane data measurably complained
about: six of twelve clicks landed between the rungs) while keeping its spirit intact:

**Provenance widens a distribution. It never multiplies fit.** Fit×confidence blending was
rejected three times and stays rejected; the wall is structural (see domain-model
invariants 1–2). The actual widths per rung are a named volatility area, calibrated from
the accumulating ruling corpus.

This also answers "does unreviewed evidence score": yes, wider. Review is the top rungs of
one ladder, not a separate flag.

### S9 · The Scorer is pool-scoped; rank is the only sort key · `demonstrated` (pairwise-ranking/rank-pool.md) · supersedes S1, S4, S5

The operator's actual question is "which 5 are my front runners," not "which openings clear
a threshold." `P(value > bar)` answers a question nobody asked and forces `bar` into being
a dial with no natural value (open-questions.md OQ9's "placeholder set off eleven
observations, seven synthetic"). Sorting the pool on `P(rank ≤ top_k)` (expected-rank
tiebreak) answers the real question directly, needs no `bar`, and reshuffles correctly as
openings enter and leave the pool — exactly the behavior the operator wants when a strong
new opening should visibly bump a weak one out of the top 5.

The Scorer changes shape to make this possible: it no longer scores one opening in
isolation against a fixed threshold. It scores every `screening`-stage opening jointly in
one Monte Carlo run, so each opening's rank is a property of where its samples land
relative to every other opening's samples in the same draw — not a per-opening scalar
comparable only after the fact. `bar` is deleted, not deprecated: it sorts and filters
nothing, anywhere (domain-model wall 7).

**Rejected:** keeping `P(> bar)` as a secondary sort or display value alongside rank —
two ranking signals invite the operator to reconcile disagreements between them, which is
exactly the kind of manufactured precision wall 4 rules out. **Rejected:** scoring openings
independently and then sorting the independent scores — that is `P(> bar)` with extra
steps; it cannot express "my top 5 changed because a new opening entered," which is the
whole point.

### S10 · Reach and the cliff retire; the rank band is the only "room left" signal · `demonstrated` (pairwise-ranking/rank-pool.md) · supersedes S4, S5

Reach's job — describing how much upside remains — and the cliff's job — flagging an
opening no realistic research pass could rescue — are both already answered by a rank
distribution: a wide q10–q90 rank band *is* "a lot of room either way," and
`P(rank ≤ top_k) ≈ 0` under a kill-level constraint *is* "this opening cannot reach the
top K," read directly off the same trace every other number comes from. Computing reach as
a second scored pass (`resolve_favourably` against a hypothetical best case) and the cliff
as a separate analytic ceiling check duplicated information the rank band already carries,
in two more fields the operator had to learn to read.

**Rejected:** keeping reach as a quantile band on the old standing scale — redefining reach
instead of retiring it, considered and rejected (rank-pool.md §Agreed): the rank band
already covers "room left" without a second number needing its own explanation.

### S11 · Dimension rulings retire; `AssertionRuling` is the only Ruling type · `demonstrated` (pairwise-ranking/rank-pool.md) · supersedes the Ruling section's original two-type design

`DimensionRuling` — a continuous `(mean, settledness)` pin over a whole dimension,
superseding every assertion under it — existed to let the operator declare a target
"settled" and stop the Scorer from moving it. Pool-scoped rank removes the need: rank is
recomputed fresh from assertions on every read, across the whole pool, so there is no
per-target aggregate value for a pin to override, and no operator action currently writes
one (the rating-page pin form retired with it). The research planner's use of
`DimensionRuling` settledness as a "stop researching this target" signal falls back to
plain assertion-derived uncertainty; it re-researches a target until its turn/action-cap
budget runs out rather than stopping early on an operator pin.

**Rejected:** converting existing `DimensionRuling` rows into priors or into synthetic
pairwise comparisons — no conversion of retiring data into the new model (rank-pool.md
§Approach). The `dimension_rulings` table stays in the database, unread, as historical
record; no migration drops it.

### S12 · Constraints retire as a target family; every scored target is a weighted dimension · `demonstrated` (constraints-and-rubric.md) · supersedes S2

S2's argument was measured against `P(overall > bar)`: to drag a perfect company below
neutral via additive weight, a constraint would have to outweigh all seven dimensions
combined. That threshold no longer exists (S9) — the queue sorts on `P(rank ≤ top_k)`, so a
constraint only needs enough weight to sit below the K-th best opening, not below a fixed
neutral point. Measured: `location` at weight 6 of 31 total sinks an otherwise-Strong
opening to `P(top 1) < 0.1` against a clean competitor (`tests/test_scorer.py`). Former
constraints (`location`, `internal_culture`, `extractive_business`) are now ordinary
`rubric.yaml` dimensions, scored by the same shrinkage math as every other dimension — no
separate `ConstraintRange`/tolerability-range machinery, no situation-label vocabulary.

**Rejected:** collecting a discrete situation label per constraint instead of `Fit`
(open-questions.md OQ14's proposed direction) — moot once constraints aren't a separate
target family; `Fit` is the single vocabulary for every scored target.

### S13 · `location` absorbs distributed-work quality; one ladder, one weight · `demonstrated` (constraints-and-rubric.md) · supersedes the `distributed` half of S12

S12 split location into two dimensions: `distributed` (how genuinely remote the company is)
and `location` (whether the arrangement is workable at all). Operator's read: the two
already covaried — a remote-first company is also trivially workable, and "must relocate"
only arises when the company isn't remote — so they're one severity ladder, not two
independent axes: remote-first (Strong) > remote-as-option or hybrid-with-a-bad-commute
(Mixed) > must relocate (Poor). Merged into `location` at its original weight 6, not the
summed 11, because the two dimensions were measuring overlapping evidence, not orthogonal
risks. Kept the `location` slug (not `distributed`) so existing `location` assertions stay
valid without a migration — broadening what the slug means costs nothing; renaming it would
have orphaned every existing assertion under the old slug.

**Rejected:** keeping both dimensions and just tuning their weights — the operator's ladder
description puts hybrid-with-mandated-office-days in Mixed, not Poor, which only the merged
ladder expresses; keeping them separate would still special-case that severity call.

---

## Evidence model

### E1 · One claim, many sources · `demonstrated`

Entering each source as its own claim double-counts corroboration — the confidence tiers
already encode cluster size, and shrinkage then reads correlated sources as independent
agreement (measured: n=3 +0.750 vs honest n=2 +0.667). One claim; citations as a list;
each citation carries an `independent` flag, a **verbatim quote** (validation is ctrl-F,
not a scroll — scrolling pages of reviews is "untenable"), **host and provenance as
separate fields** (a job board's mirror of an official req broke the single enum), and
`source_date` (urgency is blind without it — null on all four seed companies).

### E2 · Fit and confidence/provenance are separate axes, always · `demonstrated` (D3)

Admiralty Code / GRADE lineage: what a claim means and how much it's trusted are recorded
independently and never pre-blended at collection time. Blending destroys information that
can't be recovered.

### E3 · The human's raw gesture is kept; only the snap scores · `demonstrated` (D26)

Fit/provenance entered as one click on a 2D plane; the raw position is stored for the
calibration corpus and is structurally invisible to scoring. **The operator may be noisy;
the system may not manufacture precision.** First real use: 12/12 entries via the plane,
zero dropdowns, and the click clusters immediately exposed the missing confidence rung.

### E4 · Companies and openings are separate entities · `adopted`

Evidence attaches at the right level (mission/trajectory/culture/extractive → company;
stretch/comp/location → opening); openings inherit company evidence; the opening is the
scored, applied-to unit. Multiple reqs at one company share the expensive research.
**Unscreenable** (no requisition link) is a distinct intake state, not a low score — the
prototype provably emitted wrong guidance without it.

### E5 · Research is multi-pass, append-only, with an explicit contract · `demonstrated` (D14), contract `adopted` (O6 fix)

Companies are touched several times; passes see prior evidence and target gaps; the queue
must show "what changed since you last looked." The contract adds what run 1 proved
missing: **incidental evidence files free against any target, including settled ones**, and
a pass may **nominate a settled target for reopening** (routed, not auto-acted — the
anti-churn rule until a better one is earned). Run 1 had to smuggle two material facts out
as mismatches; that channel is gone.

---

## Rubric

### R1 · Stretch & Frontier is an inverted U keyed to personal ability · `demonstrated` (D15)

Poor at both tails (well-trodden personal pattern; or no realistic path to qualified);
Strong = stretch *plus* a foundation to climb from. Résumé–JD alignment folds in here — it
locates the edge, so the research pass needs the operator's extended résumé (private
config, injected at runtime). Requisition level is the strongest single signal. Took two
calibration rounds to converge; expect it to keep moving.

### R2 · Organizational pace folds into Stretch · `provisional` (D16)

Different mechanism (frequency of reps vs. height of bar) — exactly the shape that later
earns its own dimension. Watch it.

### R3 · Compensation scores against a single configured baseline · `demonstrated` (D8, D23) · superseded by R6

Poor below, Mixed at, Strong above; no justification branching. **The number is private
config, untracked from day one** — the prototype let it leak into committed files and had
to accept that; the clean build doesn't repeat it.

### R4 · Rubric text is load-bearing and versioned · `adopted` (from D25's fix)

Definitions are sliced verbatim into research prompts and review screens — proposal and
review judged against identical words. Every rubric change carries a reason; the change log
*is* the dimension-stability instrument.

### R5 · Peer caliber demotes generic "we do code reviews" language to non-signal · `demonstrated`

Measured against the live corpus (`data/live/screen.db`): every plain mention of code
review / mentorship / collaboration existing (10 of 10 in the peer-target assertion set)
landed `Mixed` regardless of company, and never once co-occurred with a `Strong` rating.
The `Strong` cases were categorically different — a named senior IC/leadership hire, a
substantive engineering-blog post, a stated hiring-bar/interview-process detail, or a
concrete practice tied to a stated outcome. Generic process language is cheap to put in
any posting; specific, hard-to-fake claims are not. `fit_anchors`/`look_for` rewritten to
score on specificity rather than topic presence — boilerplate now reads as `Poor`-tier
(no signal), not `Mixed`.

Considered and set aside: folding "competes for top regional talent" into a new
dimension. Comp already carries a large share of this signal for the affected weight
budget; a new dimension would double-count without new information (tracked as an open
question, not built).

### R6 · Compensation asks a likelihood question against a private baseline, not a flat band · `adopted` · supersedes R3

Still a single configured baseline (`SCREEN_COMPENSATION_BASELINE`), never committed — D8/D23's
privacy discipline is unchanged. What changed is the framing: "would total compensation
likely be higher than baseline" instead of a flat Poor/below Mixed/at Strong/above band,
following from S12 (compensation is now an ordinary dimension, not a constraint the old
band language was written against).

---

## Workflow

### W1 · Obtainability never scores · `demonstrated` (D24), home `adopted`

As a fourth multiplicative factor it cost 14–21× in the tail (P(> bar) lives in the tail;
mean-intuition says ~2× and is wrong), and `open_application`'s ceiling put every cold-apply
company over the cliff — most of the real job market declared dead on arrival. It is also
the one axis an **action changes** rather than research reveals; scoring it de-prioritizes
exactly the companies where acting helps most. New home: assertions against a
**non-scoring target** — same collection pipeline, a queue lens for display, structurally
excluded from standing. Promoted to its own model only if a later stage needs approach-EV
(prototype O7). "Rise above the noise" (cover-letter leverage, who do I know) lives here:
collected, not modeled.

### W2 · The product is ranking plus routing, not a to-do generator · `adopted`

Directive recommendations ("do this human action next") are dropped. What survives:
a **ResearchQueue** the operator batch-authorizes, an **Inbox** of items genuinely needing
their judgment, and **affordances** collected as data on the opening. Run 1 measured a 6:1
attention-waste ratio when everything funneled to one triage screen; of 18 model-raised
items, 2–3 needed a human. Corroboration work routes to the agent, never to the operator.

### W3 · VOI means "would this change what happens," not "how far does standing move" · `adopted` (from O5)

If the outcome is the same either way, the research was worthless however far P moved.
This framing yields the stopping rule for free: when no affordable research changes
anything, act. Costs are **configured numbers the operator owns** — no duration tracking
(the one measured cost showed guesses off 2–4×; configured-but-owned beats
measured-but-fussy for a single-user tool).

### W4 · Batched "does this override generalize?" screen — retired, not carried forward

The prototype's D27 asked a batch-wise generalization question (`rubric-edit` /
`example-only` / `one-off`) after a sit-down review of all entries. That was
instrumentation for the prototype's own Q5 ("is the rubric durable, or does accuracy
come from accumulated cases?") — a question about closing the prototype phase, not a
review interaction the operator found efficient and wants reproduced. **Do not build
this pattern.** The review UX was left open for the clean build to design from what's
actually efficient for the operator; what it settled on is the queue and per-opening
rating view in `src/screen/web/`.
### W5 · Precedent retrieves and shows; it never decides · `demonstrated`-adjacent (O8)

"You rated a similar claim Mixed at Company A" — the operator agrees or not. Auto-closing
destroys the override measurement exactly where the system is most confident, and locks
thin first rulings in as law. The operator's measured agreement rate with shown precedent
is the only argument that could ever justify auto-close.

### W6 · Triage vocabulary is per-kind · `demonstrated` (D25)

"Is this true" (corroborate), "what does this mean" (interpret), and "should the rubric
change" (rubric feedback) take different answers; one generic status enum measured nothing.
Priority and disposition are independent axes.

---

## Deleted, with reasons

- **Hypothesis entity** — a symptom of two defects, both fixed: D2 barred thin claims from
  scoring (S8 scores them, very wide) and passes couldn't file incidental facts (E5's
  contract can). Interpret items → undetermined-fit assertions; mismatches → rubric
  feedback in the Inbox.
- **Directive action recommender** — W2.
- **Duration instrumentation of human actions** — W3.
- **Bespoke obtainability state table** — W1.
- **`P(> bar)` as a total order** — it never was one (everything below the bar ties at
  exactly 0.00); S4's cliff section replaced the pretense.
