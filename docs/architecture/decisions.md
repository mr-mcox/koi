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

### S14 · Provisional similarity verdicts widen a rung below `model_proposed`; a confidence gate, never a blind one · `provisional`

The operator's comparison attention was going to near-duplicate pairs on one dimension
(`location`) instead of novel ones. A two-stage pipeline answers it: a coarse cosine filter
over per-dimension digest embeddings finds candidate pairs (cheap, local, same-dimension
only — similarity on one dimension is never evidence for another); a fine-stage verdict
provider rules each candidate `a`/`b`/`tie` with its own calibrated confidence. Below a
confidence threshold, nothing is emitted — the pair surfaces to the operator exactly as if
the pipeline didn't exist; there is no default verdict for a pair the provider itself isn't
sure about. At or above threshold, the verdict becomes a `Comparison` with
`provenance=provisional` and a per-provenance Thurstone beta wider than an operator
ruling's — S8's rung ladder, extended: operator-ratified narrowest, a confident provisional
verdict at the `precedent_matched` rung (narrower than `model_proposed`, never as narrow as
`ratified`), gated like a rung rather than built as a separate mechanism.

**Why this isn't W5's auto-close:** the batch fit's dedup-to-latest reduction makes "until I
override" literal — a later operator ruling on the same pair always displaces an earlier
provisional verdict, regardless of how confident the provider was. A provisional verdict
never overwrites an existing operator ruling; it only fills a gap no operator has looked at
yet, exactly as reversible as any other unreviewed assertion.

A provisional verdict can be directional (`a` or `b` wins), not only a tie — in scope by the
operator's explicit choice, to avoid relitigating "A beats B, C looks like B" as a fresh
judgment every time a similar pair surfaces. Scoped to pairs with no existing operator
ruling; an existing ruling is never challenged by a provisional verdict on the same pair.

**Rejected:** a single-stage cosine-only kernel (emit a tie whenever digest cosine clears a
threshold, weighted by how far above). Measured against the live pool: near-duplicate
*digests* are rare, and the ones that exist don't carry enough weight to move a
high-rubric-weight dimension. The real signal worth suppressing is rubric-semantic
similarity, not digest-text similarity — cosine is a crude proxy for it and misses cases a
human would call obviously similar (two "largely remote, no twin-cities-office" postings can
have very different digest text). **Rejected:** emitting a provisional verdict regardless of
the provider's own confidence — unconditional application is exactly W5's auto-close failure
mode; the confidence gate is load-bearing, not an implementation detail.

**Addendum (picker suppression is exclusion, not a covariance nudge):** the rung-widened
beta above was measured, twice (pre- and post-Jev-pivot), not to move the picker's choice at
all against a real quality gap on a high-weight dimension — `sqrt(weight_a)/sqrt(weight_b)`
can exceed what one widened tie's `dim_var_diff` reduction can overcome, so "the operator
never sees the near-duplicate pair again" cannot be delivered by weight alone. The operator's
actual bar is stronger than "down-weighted": "what I really care about is whether *I* do not
see that near duplicate" (2026-10-01). The picker now hard-excludes any (pair, dimension)
whose latest comparison is `provenance=provisional` — not scored, not in the running — while
an operator ruling on the same pair stays askable exactly as before (variance-decayed, never
excluded). This reads as auto-close unless paired with retrieve-and-show: `/compare/review`
lists every excluded pair the operator hasn't ratified, and opening one routes into the
ordinary compare form for that exact pair — submitting a ruling there is the override, via
the same dedup-to-latest reduction that already displaces a provisional row with a later
operator one. No new override mechanism; the beta/rung language above still describes the fit
weighting, the exclusion is a separate, additional picker-level decision.

**Addendum (the coarse cosine gate was removed, not kept as a pre-filter):** the first real
`/compare` session surfaced a `location` pair Jev should have unanimously ruled on, but Jev
was never called — `candidate_pairs`'s cosine gate (τ=0.85) rejected it first. This is the
same failure mode measured during the pivot (scouting F-SC3: only 1 of 63 `location`-digested
openings in the live pool ever clears τ=0.85) landing in the live flow, not a new one. The
coarse gate's justification was bulk cost control ahead of an O(n²) scan across the whole
pool; the live flow never does that scan — `_provisional_comparison_for_suggestion` checks
exactly one picker-suggested pair at a time, so there was no fan-out to economize on, and Jev
is cheap enough that pre-filtering a single pair bought nothing while actively blocking the
case Jev exists to catch (rubric-similar, textually-different digests). Jev is now called
directly on every suggested pair with cached digests on both sides; `fastembed`,
`src/screen/embed/`, `similarity_tau`, and the unwired bulk `provisional_verdicts()` composer
were removed, not retained as dead code.

**Addendum: The "Variance Decay" Loop and Digest-Aware Exclusion:** The original design explicitly chose to leave operator rulings in the pool, assuming variance decay would naturally suppress them. This failed: `_latest_per_pair` intentionally drops old operator rulings to keep only the newest, so asking the operator twice yields static variance, creating an infinite loop for dead-heats at the boundary. The fix was digest-aware hard exclusion: the picker now structurally excludes any pair/dimension whose latest comparison is an operator ruling, *unless* the underlying digest versions (assertion counts) have changed since the judgment, proving new evidence exists.

**Addendum: Shift to Upside-Discovery:** The picker originally forced candidate pairs into dead-heats via a `closeness` multiplier, and mathematically zeroed out relevance for roles safely inside the Top 5 via `p*(1-p)`. This aggressively penalized high-variance unknowns. `closeness` was removed, and boundary weight was flattened to `p_top_k` (relevance over squabble), so the system now pits high-upside unknowns against known baselines for maximum information gain rather than hunting for perfect ties.

### S15 · The prior's shape is Gaussian; D6's Uniform survives as moments only · `demonstrated` (measured below) · amends S1/S3

D6 and S3 specify an unexamined dimension as `Uniform(-1, +1)`, and `stats_for_target` still
computes exactly D6's moments (`mean = n·m/(n+1)`, `half_width = 1/sqrt(n+1)`, generalized to
provenance weights per S8). The **sampler** does not draw a Uniform. `_sample_dimension_gaussian`
draws `Normal(mean, half_width/sqrt(3))` — same mean, same variance, different tails.

The reason is the posterior seam, not convenience. S9 scores the pool jointly, and S14's
pairwise fit returns a multivariate Gaussian (`compare.py`'s Laplace approximation); openings
a comparison has touched *must* draw from it. If uncovered openings drew Uniform while covered
openings drew Gaussian, the two groups' samples would not be draws from one comparable family,
and a rank computed across them would depend on which seam an opening happened to arrive
through. One family, variance-matched, keeps the rank meaningful.

**Worked check (7 equal dimensions, 400k samples): the shape is invisible where it is read.**
Opening A fully examined and mediocre (every dimension mean 0.45, hw 0.40); opening B stronger
where known (mean 0.50, hw 0.40) but unexamined on three dimensions (mean 0, hw 1.0):

| Draw | mean A | mean B | sd A | sd B | P(B outranks A) |
|---|---|---|---|---|---|
| Uniform (D6 literal) | +0.4499 | +0.2855 | 0.0871 | 0.1576 | **0.1846** |
| Gaussian (implemented) | +0.4498 | +0.2855 | 0.0873 | 0.1577 | **0.1811** |

The sort key is a weighted sum across dimensions, so the central limit theorem has already
made the two nearly identical — 0.35pp on the only quantity the queue reads. D6's four
required properties all survive, because each depends on the first two moments, which match
exactly.

**Measured cost, accepted:** a Gaussian puts 8.35% of a single unexamined dimension's mass
outside `[-1, +1]`, the rubric's own range, where a Uniform puts none. This is invisible at
the dimension level (no per-dimension draw is ever displayed; bands come from the rank axis,
S10) and vanishes at the rollup: `P(|overall| > 1)` is 0.001%. Clipping draws to `[-1, +1]`
was **rejected** — it would shrink variance below the stated `half_width` and break the
variance match that makes the two seams comparable, trading an invisible tail for a silent
inconsistency in the number that does get read.

**Rejected:** sampling Uniform for uncovered openings and Gaussian for covered ones — the
mixed-family problem above. **Rejected:** restating S3's prior as a Gaussian everywhere and
retiring the Uniform language — the Uniform is still the honest statement of what the prior
*means* (no reason to prefer any value in the rubric's range), and `half_width` is a more
readable parameter than a standard deviation of `1/sqrt(3)`. The Uniform defines the prior;
the Gaussian samples it.

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

### E6 · One-time backfill may UPDATE assertions in place, as a scoped exception to append-only · `adopted` (operator, 2026-10-16)

The Jev classification migration (confidence field, relevance filtering) needs existing
assertions to carry the same shape new ones do — not append corrected duplicates
alongside stale originals, which would need a "supersedes" read-path concept that doesn't
exist. The operator chose updating rows in place for this one maintenance pass (DB backed
up first), over either inventing that read-path concept or leaving pre-migration data
unfixed. This does not reopen append-only for ongoing operation — new assertions are still
never updated or replaced after intake; only this bounded backfill touches old rows, once.

---

## Rubric

### R1 · Stretch & Frontier is an inverted U keyed to personal ability · `demonstrated` (D15) · superseded by R8

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

### R5 · Peer caliber demotes generic "we do code reviews" language to non-signal · `demonstrated` · superseded by R7

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

### R7 · Peer caliber dropped — the signal isn't researchable · `demonstrated` · supersedes R5

R5's calibration held up on the wording it was scoring, but the operator determined the
underlying judgment — who they'd actually work with — needs interview or conversation
history, not public evidence a research pass can gather. Corroborated by the live corpus
(`data/live/screen.db`): 110 `peer` assertions skew heavily toward `Mixed` (68 of 110), the
least-discriminating band, consistent with a dimension research can't move much either way.
`peer` is removed outright — not converted to a manual/operator-only dimension, and not
folded into another dimension's `look_for`. This reopens OQ16's "software is core to
strategy" talent-density half, which R5 had folded into `peer`'s Strong band (named
senior hire, hiring-bar detail); it is unhomed again and stays an open question, not
resolved here.

### R8 · Stretch redefined as a discipline-preference ladder, renamed `craft_direction` · `demonstrated` · supersedes R1

R1's ability-distance/inverted-U model wasn't discriminating in the live corpus
(`data/live/screen.db`): 89 Strong / 3 Mixed / 0 Poor across 92 `stretch` assertions, almost
all keyed to bare requisition-level/title language regardless of domain — R1's own
"strongest single signal" claim had swallowed the dimension. The operator's actual use of
the concept is a discipline-preference ladder: is this a way they want to keep growing in,
independent of both `domain` (industry novelty) and `schematic` (shape of the work). New
fit anchors, verbatim from the operator: Strong = genuine mixture of AI engineering/LLM
solution design and standard ML/deep learning; Mixed = data engineering, analytics
engineering, dev ops, backend engineering (done before, less exciting); Poor = front end
engineering, embedded systems (little depth, high ramp-up cost). The résumé-alignment
mechanism and the D16 "expect overrides / least trustworthy" caveat are dropped along with
the old model — both were written against ability-distance, not discipline preference.

Slug renamed `stretch` → `craft_direction` rather than reinterpreted in place, so stale
`Strong` assertions collected under the old ability-distance semantics don't silently carry
over as if they meant something about discipline fit; re-fetch is expected. Stays in normal
research gap-detection, unlike `domain` (OQ12) — JD-legible by default, but corroborating
evidence (blog/talks/shipped-work discussion) changes confidence, and its *absence* under an
aspirational "we do AI/ML" JD is itself a negative signal.

R2's "organizational pace folds into Stretch" was written against the ability-distance
model (pace limiting how often the edge gets touched) and has no equivalent under the
discipline-preference framing; it is not carried forward and is not superseded here —
left as-is per append-only discipline, its premise no longer applies to `craft_direction`.

### R9 · Retired rubric targets are dropped at the SQLite read boundary, not migrated · `provisional`

When `rubric.yaml` renames or removes a dimension, the operator's live `data/live/screen.db`
still holds assertions, cached `dimension_digests`, and `comparisons` rows tagged with the old
slug. Rather than require a blocking migration before the app renders, the read-path mappers in
`src/screen/store/mappers.py` validate each stored `target` against the current closed `Target`
vocabulary and `warnings.warn` + drop rows whose target is no longer current. This makes the UI
and scorer resilient to rubric drift; retired evidence becomes unexamined rather than
silently reinterpreted under a renamed dimension. A migration (targeted `DELETE` for the
retired slug, then re-fetch for current dimensions) remains an option if the warnings become
noisy or if the operator wants to reclaim space. This is explicitly a tolerance seam, not a
validation rule — new writes still pass the strict `Target` Literal in `screen.types`.

Set aside: a one-time startup migration that rewrites old slugs into new ones. That would
preserve the evidence, but it directly conflicts with the rename intent for `stretch` →
`craft_direction`: stale `Strong` ability-distance assertions should not carry over as `Strong`
craft-direction claims. Dropping them is the conservative default; migration only makes sense
after the operator confirms which rows are worth re-fetching.

### R10 · `extractive_business` retired; `mission` carries the full extraction question at one band · `demonstrated`

`extractive_business` (weight 4) was the same customer-extraction question `mission`
(weight 2) already asked, split by confidence tier: `extractive_business` anchored
clear-cut/obvious cases, `mission` anchored the nuanced middle ground. The operator's mental
model doesn't segment by confidence — `mission` answers "would I want to be part of this if
it succeeds" (values), `trajectory` answers "will it succeed" (health/strategy), and
extraction is wholly a `mission` question regardless of how obvious the evidence is.
`extractive_business` is dropped outright, not folded elsewhere as a separate mechanism;
`mission`'s definition/fit_anchors now span the full range from clear-cut to ambiguous
extraction at one band. `mission`'s weight stays 2 — no reweighting to absorb the merged
range. D19's shape (Strong is the outcome of looking and finding no extraction, not the
default of not looking) carries over unchanged into the merged anchors.

`mission`'s prior text also asked whether an 'AI-powered' claim was real product leverage
or investor decoration, blended into the same Poor/Mixed/Strong anchors as the extraction
question. The operator's segmentation puts AI-narrative authenticity under `trajectory`
("will it succeed" — a hype-driven strategy is a trajectory risk) rather than under
`mission` (values) or `agentic` (a distinct question: tooling quality, not narrative
honesty). `trajectory`'s `look_for` now names hype-vs-defensible-strategy generally, with
AI framing as one instance rather than a dedicated callout — it wasn't judged to carry
enough independent weight to need its own fit_anchor language.

Retired at the SQLite read boundary per R9's generic mechanism (`Target` Literal shrinks;
`src/screen/store/mappers.py`'s existing validate-and-drop path requires no new code).

**Rejected:** keeping `extractive_business` as a confidence-tiered sub-case of `mission`
instead of dropping it — the confidence split was the redundancy being named, not a
distinction worth preserving. Also rejected: giving AI-narrative-authenticity its own
dimension or fit_anchor — too minor a signal to warrant a dedicated callout; if `mission`
scores poorly while an opening still ranks high in practice, that's deferred as a future
problem, not solved by adding structure now.

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
