---
name: open-questions
type: open-questions
date: 2026-08-21
provenance: distilled from prototype hand-off conversation; no committed codebase at writing
companions: decisions.md, learnings.md
---
# Open Questions — Clean Build Seed
Distilled 2026-08-21. Each entry states what would settle it, so the clean build defers
these deliberately instead of deciding them by accident. None should be answered by
architecture; the architecture's job is to keep each one cheap to answer later.

---

## 1 · Provenance-variance geometry — the widths per rung

S8 (seed DECISIONS) says provenance sets variance; nobody knows the actual widths for
model-proposed / precedent-matched / ratified, nor how source count folds in.

**Settled by:** the accumulating ruling corpus — override direction and magnitude per rung.
The prototype's one measurement (all confidence overrides upward, model too cautious) is
the first calibration point. Steel-thread first; expect to retune.

## 2 · Rung and anchor placement — are three fit buckets right?

Six of twelve raw plane clicks landed between the old confidence anchors. The same
instrument now watches fit: if clicks cluster persistently between Poor/Mixed/Strong,
the anchors are wrong — evidence collected rather than assumed.

**Settled by:** click clustering over the raw-position corpus (dozens of rulings, not
hundreds).

## 3 · The anti-churn rule for reopening settled targets

The pass contract lets a pass nominate a settled target for reopening, routed to the
operator. That's the placeholder rule. If nominations are frequent and always approved,
routing is friction; if the model churns, routing is the only defense.

**Settled by:** the nomination log — approval rate and repeat-nomination rate.

## 4 · Research targeting: rule vs. model (prototype O4, narrowed)

The recommender is gone, but the ResearchQueue still ranks targets, and the arithmetic is
provably indifferent between unexamined constraints (exact k-way ties). A hand-written
cheapness order breaks ties today.

**Settled by:** divergence — the operator batch-authorizing a *different* target than the
rule ranked first, clustering on the tiebreak. That is direct evidence the choice needs
judgment the arithmetic can't supply.

## 5 · Does approach-EV ever get modeled? (prototype O7)

Nothing can show an intro call paying off versus a cover letter, because obtainability
deliberately has no number. Two ways out were recorded: accept it forever, or give
obtainability an expected-value used *only* for comparing approach actions (never touching
standing).

**Settled by:** real applications and outcomes — the numbers don't exist before then, and
fitting a model to no data is the rejected failure mode. Until then: collect, don't model.

## 6 · When does precedent earn auto-close? (prototype O8)

Retrieve-and-show is the standing decision (seed DECISIONS W5). Auto-close destroys the
override measurement where the system is most confident and locks thin rulings in as law.

**Settled by:** the operator's measured agreement rate with shown precedent. ~9 in 10 over
a real corpus makes auto-close arguable; anything less confirms the caution.

## 7 · Does organizational pace earn its own dimension?

Folded into Stretch provisionally — different mechanism (frequency of reps vs. height of
bar), which is exactly the shape that later separates.

**Settled by:** pace-based overrides or rubric-feedback items that Stretch's definition
can't absorb cleanly.

## 8 · Rise-above-the-noise: collect-only, until when?

Cover-letter leverage and warm paths are collected as non-scoring assertions. Whether any
of it ever informs ranking (as distinct from approach) is open — and the résumé-alignment
half already moved *into* Stretch, so the boundary may move again.

**Settled by:** later-stage need. If the holding area / application stages never miss it,
it stays collect-only.

## 9 · Dials: `bar`, band thresholds, tolerability ranges

All placeholders set off eleven observations, seven synthetic. The current bar makes
"heavy, not fatal" constraints fatal — accepted knowingly (lots of fish), and it resolves
the moment `bar` moves.

**Settled by:** batch ranking over a real queue. If the live section is empty or
everything's a contender, the dials move — the model's shape doesn't.

## 10 · Lightweight vs. heavy screening at intake

One intake adapter exists (hand-pasted link → full research pass). Whether a cheap
pre-screen is worth building before feeds exist is untested, and it's a volume
optimization — the prototype deliberately never tested volume.

**Settled by:** feed volume actually exceeding what full passes can absorb (at ~$1.10 and
3.5 minutes per pass, that threshold is further out than intuition suggests).

## 11 · How many passes does a decision take?

Q3's real metric, with zero observations. The search cap should not move until there are
several runs to compare.

**Settled by:** per-company lifetime instrumentation across the steel thread's one-off and
batch phases.

## 12 · Should "domain" research split into gatherable evidence vs. operator-only rating?

domain-model.md's wall on domain coolness ("operator's own reaction — manual entry only,
never researched") is right about the *rating* — no automated pass can know what fascinates
the operator. But the loop-search manual test (2026-09, one real opening) showed the
planner burning its entire search budget chasing `domain` as an ordinary gap anyway,
because `rubric_text_for_baml()` renders it identically to every researchable dimension —
same definition/fit-anchors/look-for shape, no signal that this one can't be closed by
search. Meanwhile the material under the rating — what the business does and how it's
accomplishing it — is plain factual evidence, gatherable the same way mission/stretch
evidence is.

Direction this ought to take: exclude `domain` from research gap-detection now (cheap,
loop-search-internal, no rubric change). Don't add a dedicated evidence-gathering target
for it yet — defer that until there's an actual consumer, which is most likely
`PrecedentLookup` (open-questions #6 lineage, domain-model.md's roadmap after the steel
thread): comparing a new opening's domain against companies the operator has already
ruled on ("similar to Company Y that Matthew was interested in") is exactly the shape of
judgment a fit-guess-by-search can't supply, but a factual company summary plus precedent
retrieval could.

**Settled by:** `PrecedentLookup` reaching build. At that point it needs some input to
compare against precedent, and whether that's a dedicated non-scoring target (e.g.
`non_scoring:company_profile`) or just the raw fetched page text already sitting in the
transcript is a real design choice to make then, with a real consumer in front of it —
not a guess to make now.

