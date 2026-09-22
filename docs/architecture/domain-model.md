---
name: domain-model
type: domain-model
date: 2026-08-21
provenance: distilled from prototype hand-off conversation; no committed codebase at writing
companions: decisions.md, prototype-decisions.md
---
# Domain Model — Clean Build Seed

Distilled 2026-08-21 from the prototype. Entities and collaborators derived from what real
use taught us, organized for a walking-skeleton build: the steel thread exercises the three
genuinely novel decisions first, and everything else bolts on without touching the core.

The prototype's full reasoning is distilled in `prototype-decisions.md` (cited below as
D-numbers), which also defines the Company A–D pseudonyms used across these docs.

---

## Bounded contexts

Four: **Intake** (the outside world becomes screenable units), **Evidence** (claims about
companies and openings accumulate), **Judgment** (claims become rankings; the operator's
rulings become calibration), **Workflow** (what surfaces, to whom, in what order).

---

## Intake — a port

**Feed** adapters produce a **CandidateOpening**. v1 adapter: a hand-pasted link. Later:
lightweight screener, job feeds, email — all behind the same port.

Intake's one job is deciding *is there a screenable unit here*. Output is either an
`Opening`, or an explicit **unscreenable** record with the reason ("no requisition link").
Unscreenable is a distinct state, not a low score — the prototype's Company C case showed
that without it, the system emits provably wrong guidance (`research location` when the
real next step is "get a real req link").

## Evidence — the heart

### Company

An evidence container with identity. Company-level targets:

- Dimensions: mission fit, trajectory & leverage, peer caliber, agentic/AI engineering
  culture, domain coolness (measures the operator's own reaction — manual entry only,
  never researched; an automated pass leaves it unexamined rather than guessing), internal
  culture, extractive business.

### Opening

**The scored, actioned, applied-to unit.** References a Company; a second opening at a
known company inherits all company-level evidence free.

- Role-level dimensions: stretch & frontier, compensation, location compatibility
  (covers both remote/distributed-work quality and physical workability on one ladder,
  decisions.md S13).
- Non-scoring targets: obtainability / rise-above-the-noise (see the wall below).
- Affordances — collected data, never directives: where to apply, cover letter accepted,
  posting date, requisition level.
- Pipeline stage: `screening → pursuing / applied / closed`. Deliberately thin; other
  systems do real application tracking. No `outcome` sub-typing on `closed` — implemented
  in `Opening.stage`; `screening` is the only stage that ranks or draws research budget.

### Assertion

One claim, append-only. The prototype's central format finding: granular, auditable,
pointed at exactly one target.

- `target` — one dimension, at company or opening level. Non-scoring targets accept
  assertions; the Scorer ignores them.
- `fit` — Poor / Mixed / Strong, **or undetermined** (well-sourced fact, verdict genuinely
  open — e.g. a recent acquisition at Company A: narrow on sourcing, wide on meaning). One
  observation may yield several interpretations, each its own assertion against its own
  target.
- `provenance` — who judged this, which sets the variance (see Scorer):
  `model-proposed` → `precedent-matched` (rhymes with the operator's ruling corpus) →
  `ratified` (the operator ruled). Ratified is still noisy — the operator is a noisy
  signal too.
- `citations[]` — see below.
- Raw plane position when human-entered — kept for the calibration corpus, invisible to
  scoring (D26).

### Citation

Per source: URL, **verbatim quote** (validation becomes ctrl-F, not a scroll), `independent`
flag (one claim with three correlated sources is one claim — the corroboration
double-counting bug), and **host and provenance as separate fields** (a job board's mirror
of the company's own req is official content on an aggregator host; the prototype's single
enum forced a lie). `source_date` — required where obtainable; urgency is blind without it.

### ResearchPass

Assigned targets, search/token budget, full instrumentation (searches, tokens, wall clock —
the Q3 meters). The contract, amending the prototype's D14 for its O6 defect:

1. Passes append; nothing is replaced.
2. Budget is spent only on assigned gaps.
3. **Incidental evidence is filed free** against any target, including settled ones.
4. A pass may **nominate a settled target for reopening**; the nomination is routed, not
   auto-acted, which is the anti-churn rule until a better one is earned.
5. Every claim carries citations from URLs the tooling actually returned.

## Judgment

### Rubric

A **versioned entity, not config**. Dimension definitions whose text is load-bearing —
sliced verbatim into research prompts and review screens, so proposal and review are judged
against identical words. Weights, the dials (`top_k`), and configured action costs. **Every change carries a reason; the change log is
the dimension-stability instrument** (the prototype's Q2/Q5).

The compensation baseline and the operator's extended résumé are **private config**,
injected at runtime, never committed (D23).

### Scorer

A pure domain service, **pool-scoped**: `(every screening opening's assertions, rubric) →
per-target distributions sampled jointly across the whole pool → a rank distribution per
opening`. Stateless, deterministic given a seed. The joint trace is the source of truth —
rank, `P(rank ≤ top_k)`, and the pool's top-K settledness are computed from it on read, not
stored as separately-frozen fields that could drift out of agreement with it. Scoring one
opening in isolation is not a supported operation: rank is a property of the pool, and
`/openings/{id}/score` scores the whole live pool to report one opening's slice of it
(see pairwise-ranking/rank-pool.md).

The modeling decision carried over unchanged from the per-opening Scorer it replaced:
**an assertion is a noisy measurement of what the operator would conclude, and provenance
sets the noise.** Unexamined → maximal width (D5). Model-proposed → wide.
Precedent-matched → narrower. Ratified → narrowest, not zero. **Provenance widens a
distribution; it never multiplies fit.** Blending the two axes into one number is the
thrice-rejected mistake (walls 1–2). The Scorer consumes `Assertion.provenance` as an
already-assigned input; how a Ruling or PrecedentLookup match comes to set that value is the
Ruling mechanism's concern, not the Scorer's (see Ruling, below).

Each dimension is a Gaussian per opening, variance-matched to the shrinkage formula that
produced the old per-opening Uniform (`std = half_width / sqrt(3)`), sampled jointly across
the pool from a mean vector and a covariance matrix — diagonal (independent openings)
until compare.md fills in measured cross-opening correlation from operator comparisons.
`overall` is the weighted sum of every dimension in `rubric.yaml`, including `location`,
`internal_culture`, and `extractive_business` — there is no second, differently-scored
target family. Rank is computed by sorting each Monte Carlo sample's `overall` score across
openings; `P(rank ≤ top_k)`, expected rank, and rank quantiles (q10/50/90) are read off the
resulting rank matrix — none of them a per-opening scalar computed independently of the
rest of the pool.

`standing`, `reach`, and the cliff ceiling do not exist in this model (S9–S11 in
`decisions.md` supersede S1, S4, S5): a wide-open opening's rank distribution already spans
from contender to irrelevant, and `P(rank ≤ top_k)` already collapses to ≈0 for an opening a
kill-level dimension has ruled out. There is no second regime to compute, store, or
display — rank is the only sort key, everywhere.

Implemented in `src/screen/score/` (`types.py`, `scorer.py`, `loader.py`), verified against
synthetic pools and real seed data.

### Ruling

`AssertionRuling` is the one Ruling type: a categorical confirm/override on one assertion.
`DimensionRuling` — the operator's continuous `(mean, settledness)` placement over a whole
dimension, superseding every assertion under it — is retired (pairwise-ranking/rank-pool.md;
decisions.md S9–S11 supersede S1/S4/S5). Rank is a pool property computed fresh from
assertions on every read; there is no per-target aggregate for an operator pin to
supersede, and no UI writes one. The `dimension_rulings` table stays in the database,
unread, rather than migrated away — its rows are historical record, not live input.
Reviews are not required to be worked in a fixed batch-then-generalize shape (D27's batch
screen was prototype instrumentation for one pivot question, not a UX pattern — see
`decisions.md` W4). The accumulating `AssertionRuling` corpus is the calibration data for
everything: confidence-ladder geometry, precedent matching, the encodability answer, and
(pairwise-ranking) the pairwise comparison log compare.md adds alongside it.
**Open tension, not yet resolved:** provenance may belong to Ruling rather than being a
field Assertion carries directly. Candidate mechanism: an assertion's rung is *derived*
from whether and how it links to the Ruling corpus — no link → `unexamined`; a
model-proposed assertion with no Ruling → `model_proposed`; a `PrecedentLookup` match to a
Ruling on a *different* assertion → `precedent_matched`; a direct Ruling *on this
assertion* → `ratified`. This is consistent with `PrecedentLookup`'s sketch below but isn't built —
neither `Ruling` nor `PrecedentLookup` exist as code yet, and today `Assertion.provenance`
is simply asserted by whatever wrote the assertion (always `model_proposed` from the
current extraction pipeline). Whoever builds `Ruling` needs to settle this before
provenance can be treated as anything but an opaque input.

### PrecedentLookup

Reads the Ruling corpus. **Retrieve and show, never decide**: "you rated a similar claim
Mixed at Company A." Also the mechanism behind the `precedent-matched` provenance rung. If
the operator agrees with shown precedent nine times in ten, auto-closing becomes arguable —
with the measured agreement rate as the argument. Not before.

## Workflow

The product is **ranking plus routing** — signal through noise, most promising rises — not
a to-do generator. Three thin pieces:

- **Queue** — a projection, not an entity. Ordered by pool-scored rank (`P(rank ≤ top_k)`,
  expected-rank tiebreak), with rank bands and a top-K settledness readout; "what changed
  since you last looked" (re-entry is the primary mode); reorder lenses for urgency and
  obtainability. `bar` is not a sort key or filter anywhere in this projection
  (pairwise-ranking/rank-pool.md; decisions.md S9–S11).
- **ResearchQueue** — proposed research targets ranked by value of information, where VOI
  means *"would knowing this change what happens to this opening"* rather than "how far does
  standing move." The operator batch-authorizes. The stopping rule falls out: when no
  affordable research would change anything, act.
- **Inbox** — only the items routed to the operator's judgment: rulings, adjudications of
  undetermined-fit assertions, reopening nominations, rubric feedback. The prototype
  measured a 6:1 attention-waste ratio when everything funneled to one screen; routing is
  the offload mechanism. Corroboration work routes back to the agent.

Costs are **configured numbers the operator assigns**, at their chosen precision. No
duration tracking — the one measured cost (review: guessed 1.5, measured 0.36 median)
proved guesses wrong, and configured-but-owned beats measured-but-fussy for a single-user
tool.

### Deleted from the prototype, with reasons

- **Hypothesis** — a symptom of two defects, both fixed. Low-confidence claims parked there
  because D2 barred them from scoring (provenance-as-variance now scores them, very wide);
  facts about settled dimensions were smuggled there because passes couldn't file them (the
  pass contract now can). Its remains: `interpret` items are undetermined-fit assertions;
  `mismatch` items are rubric feedback routed to the Inbox.
- **Directive recommender** ("do this next") — collecting affordances is useful; telling
  the operator which human action to take is not the core value. Q4 answered by
  dissolution.
- **Thick ActionLog** — shrinks to pipeline-stage transitions.
- **Obtainability as bespoke state table** — now assertions against a non-scoring target.

---

## The walls (invariants, each asserted structurally in tests)

1. **Raw plane positions never reach the Scorer.** A continuous confidence next to a
   multiplication is one careless commit from confidence-as-multiplier (rejected 3×).
2. **Fit and provenance never blend into one number.** Provenance widens; it never scales.
3. **Non-scoring targets never enter rank.** Obtainability multiplied in cost 14–21×
   in the tail and put every cold-apply company over the cliff (D24's measurement) — and it
   is the one axis an *action changes*, so scoring it inverts the exploration incentive.
4. **Precision ranks; displays avoid false precision.** A single review must never produce "6.7/10."
5. **Unexamined ≠ clean, everywhere including display wording.** "Wide because negotiable"
   and "wide because nobody looked" never share a label.
6. **Assertions are append-only; rubric changes carry reasons.**
7. **Rank is the only sort key; `bar` sorts and filters nothing.** Superseded from "reach
   never becomes a sort key" — reach and the `bar`-relative cliff no longer exist to
   tempt anyone (decisions.md S9–S11 supersede S1/S4/S5).
8. **Private config stays private.** Compensation baseline, extended résumé, contact/
   obtainability details, and collected evidence data never enter committed files.

## Steel thread, and the increments after it

**Thread:** one Opening at a new Company, entered by link → one ResearchPass writes
Assertions at both levels → Scorer produces a pool-scored rank from provenance-widened distributions →
the operator rules on a handful of entries → re-score shows ratification narrowing → the
queue reflects it. This exercises the three novel decisions (company/opening split,
provenance-as-variance, pass contract) before anything is layered on them.

**Then:** a few one-offs beginning-to-end → batch several and inspect the ranking → routing
and the Inbox → PrecedentLookup (needs corpus volume) → intake adapters → holding-area view.

## Named volatility areas (expected to move; architecture must keep them cheap to move)

- Provenance-variance calibration: the actual widths per rung.
- Rung count and anchor placement (the plane clusters say three fit buckets may be wrong).
- Rise-above-the-noise: collected now, modeled only if a later stage needs approach-EV.
- `top_k`: placeholder set off eleven observations, seven synthetic.
- Whether organizational pace earns its own dimension (folded into Stretch provisionally).
