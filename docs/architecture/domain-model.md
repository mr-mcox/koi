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
  never researched; an automated pass leaves it unexamined rather than guessing).
- Constraints: internal culture, extractive business.

### Opening

**The scored, actioned, applied-to unit.** References a Company; a second opening at a
known company inherits all company-level evidence free.

- Role-level dimensions: stretch & frontier, compensation.
- Role-level constraint: location.
- Non-scoring targets: obtainability / rise-above-the-noise (see the wall below).
- Affordances — collected data, never directives: where to apply, cover letter accepted,
  posting date, requisition level.
- Pipeline stage: `screening → handed-off → applied → closed(outcome)`. Deliberately thin;
  other systems do real application tracking. The holding area is a view over this field.

### Assertion

One claim, append-only. The prototype's central format finding: granular, auditable,
pointed at exactly one target.

- `target` — one dimension or constraint, at company or opening level. Non-scoring targets
  accept assertions; the Scorer ignores them.
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
against identical words. Weights, constraint tolerability ranges, the dials (`bar`, band
thresholds), and configured action costs. **Every change carries a reason; the change log is
the dimension-stability instrument** (the prototype's Q2/Q5).

The compensation baseline and the operator's extended résumé are **private config**,
injected at runtime, never committed (D23).

### Scorer

A pure domain service: `(assertions, rubric) → per-target distributions → Monte Carlo trace
→ standing, reach, ceiling, band`. Stateless, deterministic given a seed. The trace is the
source of truth — standing, hits, and sampling noise are computed from it on read, not
stored as separately-frozen fields that could drift out of agreement with it.

The new modeling decision, steel-threaded first because it is the least proven:
**an assertion is a noisy measurement of what the operator would conclude, and provenance
sets the noise.** Unexamined → maximal width (D5). Model-proposed → wide.
Precedent-matched → narrower. Ratified → narrowest, not zero. This amends the letter of
the prototype's D2 (Medium/High identical — the rung-less ladder the plane data complained
about) while keeping its spirit: **provenance widens a distribution; it never multiplies
fit.** Blending the two axes into one number is the thrice-rejected mistake. The Scorer
consumes `Assertion.provenance` as an already-assigned input; how a Ruling or
PrecedentLookup match comes to set that value is the Ruling mechanism's concern, not the
Scorer's (see Ruling, below).

`standing` and `reach` are not two fields of one result — they are the same result type
scored against two different assertion sets. `standing` scores the assertions as they
actually exist; `reach` scores a counterfactual where every unexamined target has received
one hypothetical good research pass. Comparing the two pairs is what names the band
(D20, D21): `standing` is the only sort key; `reach` never sorts (it saturates — an empty
record out-reaches a researched good one); the cliff is analytic, not sampled; within-noise
neighbors are marked as such.

Implemented in `src/screen/score/` (`types.py`, `scorer.py`, `band.py`, `loader.py`),
verified against real seed data.
One open tension surfaced during implementation: constraints (location, internal_culture,
extractive_business) are scored by affine-mapping an assertion's `Fit` onto the
constraint's tolerability range, shrunk the same way a dimension is — but the prototype's
constraint model read a discrete *situation label* per constraint, not `Fit`, and
`screen.types.Assertion` has no situation-label field. This passes every acceptance test
but is an interpretive bridge nobody has confirmed reads correctly (→ open-questions.md
OQ14).

### Ruling

The operator's review event: proposed vs. final labels, the raw click, remediation path.
Granularity is open (→ `docs/features/review-ux/scouting.md` F6/F18): whether a Ruling is
always assertion-level, or whether a dimension-level Ruling is also a first-class object,
is undecided pending that feature's bearing. What's settled: reviews are not required to
be worked in a fixed batch-then-generalize shape (D27's batch screen was prototype
instrumentation for one pivot question, not a UX pattern — see `decisions.md` W4). The
accumulating corpus is the calibration data for everything: confidence-ladder geometry,
precedent matching, the encodability answer.

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

- **Queue** — a projection, not an entity. Live and over-the-cliff sections; standing/reach
  band pair; sampling-noise marks; "what changed since you last looked" (re-entry is the
  primary mode); reorder lenses for urgency and obtainability.
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
3. **Non-scoring targets never enter standing.** Obtainability multiplied in cost 14–21×
   in the tail and put every cold-apply company over the cliff (D24's measurement) — and it
   is the one axis an *action changes*, so scoring it inverts the exploration incentive.
4. **Precision ranks; bands display.** A single review must never produce "6.7/10."
5. **Unexamined ≠ clean, everywhere including display wording.** "Wide because negotiable"
   and "wide because nobody looked" never share a label.
6. **Assertions are append-only; rubric changes carry reasons.**
7. **Reach never becomes a sort key.**
8. **Private config stays private.** Compensation baseline, extended résumé, contact/
   obtainability details, and collected evidence data never enter committed files.

## Steel thread, and the increments after it

**Thread:** one Opening at a new Company, entered by link → one ResearchPass writes
Assertions at both levels → Scorer produces a band from provenance-widened distributions →
the operator rules on a handful of entries → re-score shows ratification narrowing → the
queue reflects it. This exercises the three novel decisions (company/opening split,
provenance-as-variance, pass contract) before anything is layered on them.

**Then:** a few one-offs beginning-to-end → batch several and inspect the ranking → routing
and the Inbox → PrecedentLookup (needs corpus volume) → intake adapters → holding-area view.

## Named volatility areas (expected to move; architecture must keep them cheap to move)

- Provenance-variance calibration: the actual widths per rung.
- Rung count and anchor placement (the plane clusters say three fit buckets may be wrong).
- Rise-above-the-noise: collected now, modeled only if a later stage needs approach-EV.
- Band thresholds and `bar`: placeholders set off eleven observations, seven synthetic.
- Whether organizational pace earns its own dimension (folded into Stretch provisionally).
