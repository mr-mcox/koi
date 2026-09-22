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

## 9 · Dials: `top_k` and tolerability ranges

All placeholders set off eleven observations, seven synthetic. `bar` itself retired
(decisions.md S9 supersedes S1/S4/S5) — rank is the only sort key now — but `top_k` (the
competitive cutoff the rank glyph and settledness readout are computed against) and the
constraint tolerability ranges are exactly as unmeasured as `bar` was.

**Settled by:** batch ranking over a real queue. If the top of the queue looks wrong to the
operator, the dials move — the model's shape doesn't.

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
internal to the research pass, no rubric change). Don't add a dedicated evidence-gathering target
for it yet — defer that until there's an actual consumer, which is most likely
`PrecedentLookup` (open-questions #6 lineage, domain-model.md's roadmap after the steel
thread): comparing a new opening's domain against companies the operator has already
ruled on ("similar to Company A, which the operator was interested in") is exactly the shape of
judgment a fit-guess-by-search can't supply, but a factual company summary plus precedent
retrieval could.

**Settled by:** `PrecedentLookup` reaching build. At that point it needs some input to
compare against precedent, and whether that's a dedicated non-scoring target (e.g.
`non_scoring:company_profile`) or just the raw fetched page text already sitting in the
transcript is a real design choice to make then, with a real consumer in front of it —
not a guess to make now.

## 13 · Should `Target`/BAML schema derive from `rubric.yaml`, rather than hand-sync?

Rubric dimension/constraint slugs currently need matching-by-hand updates in three places:
`rubric.yaml` itself, `screen.types.Target` (closed Literal, wall 3), and the BAML
`Assertion` schema (`baml_src/extract.baml`). A first rubric revision (v2, draft, splitting
`schematic` out of `stretch`) already surfaced the gap: the YAML can describe a dimension
nothing downstream can produce or validate yet, with nothing forcing the sync.

**Settled by:** whether this recurs. One instance is a hand-off note, not a pattern; if a
second rubric revision hits the same gap, that's evidence the sync should be generated
rather than maintained by hand.

## 14 · SETTLED — constraints retired as a target family; no situation-label question remains

Moot: constraints-and-rubric.md retired the separate constraint scoring family (S12).
`location`, `internal_culture`, and `extractive_business` are now ordinary `rubric.yaml`
dimensions scored the same way every other dimension is — `Fit` is the single vocabulary
for every scored target, so there is no tolerability-range translation left to question.

## 15 · When does migration tooling (e.g. Alembic against SQLAlchemy Core) earn its keep over hand-written SQL migrations?

score-persistence chose raw `sqlite3` + hand-mapped Pydantic models + a small numbered-`.sql`
migration runner over an ORM, deliberately: `screen.types` is already the domain model
(Wall 1/2/3 tested against it), and an ORM (SQLModel or similar) would make that model do
double duty as the persistence model too, plus tends to shape endpoints around tables
rather than the domain question being asked. Three tables, read-only endpoints — the
machinery isn't earning anything yet.

**Settled by:** either (a) migrations start needing real downgrade paths / branching
schema changes that hand-written SQL makes error-prone, or (b) the table count and join
complexity grow past what mapper functions stay cheap to hand-write for. First sign is
likely a migration that's hard to write correctly by hand, not a growing table count
alone — that's the trigger to revisit, not general unease about boilerplate.

## 16 · Does "software is core to company strategy" need its own home?

The operator's stated target profile (tier-3 companies: compete for top regional talent,
software central to strategy, not necessarily venture-backed) has two halves. The
talent-density half now lives in `peer` (R5). The "software is core to strategy" half has
no current dimension — it's adjacent to but distinct from `trajectory` ("healthy company
AND the operator's work is load-bearing"): a company can be healthy and treat engineering
as a cost center. Not built yet because it isn't known whether it's already implicit in
which postings reach intake (tier-1/2 vs. tier-3 companies may self-select before research
starts) or actually missing signal once research runs.

**Settled by:** a real case where a company clears every existing dimension acceptably but
the operator would still pass because engineering visibly isn't strategic to the business
— that divergence is the evidence a dimension is missing, not a guess now.

## 17 · Digest-similarity / cross-opening kernel prior for comparisons — rising priority

F52/F53 (pairwise-ranking scouting) named and deferred a similarity prior: replace a
dimension's diagonal covariance with a kernel over digest embeddings, so a comparison
outcome on one opening lifts a similar opening's posterior too, instead of every opening
needing its own direct comparisons. Deferred as "may never need it" when first raised.
The operator has now raised the same idea unprompted three times within a few weeks
(most recently while reviewing why the compare picker kept re-asking about `location`
across many structurally similar remote postings) — recurrence, not new information, is
what's escalating this; nothing has yet demonstrated the diagonal-covariance model is
insufficient.

Decisions W5 ("precedent retrieves and shows; it never decides") applies once this is
built: a similarity prior moves scores automatically, so it needs a decisions.md entry
placing it on S8's `precedent_matched` rung rather than auto-closing a judgment.

**Settled by:** either (a) the operator's recurring mention becomes a concrete complaint
— a specific pair the picker asked about that a similarity prior would have skipped — which
is the trigger to build it, or (b) three mentions without a concrete case is itself
enough signal to schedule it as the next bearing regardless. Whichever comes first should
be the one written down when this is picked up, not re-litigated from scratch.
