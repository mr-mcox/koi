---
name: prototype-decisions
type: decision-record
date: 2026-08-21
provenance: prototype's full D1–D27 record, scrubbed of identifying details during distillation; Company A–D pseudonyms defined below
companions: decisions.md, domain-model.md, learnings.md
---
# Prototype Decision Record — Appendix
The prototype's full decision log (D1–D27 plus open items), distilled for carry-over and
scrubbed of identifying details. The seed documents cite these by D-number. Each entry
keeps what a later reader needs: the decision, the why, and what was rejected — several
alternatives were killed by numeric demonstration, and those demonstrations are the record.

**Company pseudonyms**, used consistently across all handoff docs:

- **Company A** — the strongest seed candidate; target of the first real research pass;
  ships an agent product; became a contender after one pass.
- **Company B** — inbound contact; broken careers page; a first-technical-hire greenfield
  role; a hybrid-in-another-metro location policy.
- **Company C** — arrived with no requisition link; nothing scorable.
- **Company D** — corroborated negative culture evidence.

---

## D1 — Local web app, SQLite-backed

A queue you return to mid-session, not a CLI table or a chat-session tool. Prototype
mechanics; the clean build re-decides its own stack.

## D2 — Confidence is a threshold, never a multiplier · superseded by seed S8

Low confidence (one uncorroborated source) didn't score; Medium and High counted equally.
**Rejected three separate times across drafts:** fractional confidence weights
(0.3/0.65/1.0). Multiplying fit by confidence blurs "barely confirmed but probably true"
into "confirmed genuinely middling" — both land near the same small number, destroying the
distinction the two axes exist to keep. The rejection of *blending* is permanent; the
rung structure itself was measurably wrong (see seed LEARNINGS Q1) and is superseded by
provenance-as-variance.

## D3 — Fit and confidence stored separately, always

What a claim means vs. how much it's trusted — two labeled fields, never pre-blended at
collection. Lineage: the Admiralty Code grades source reliability separately from claim
credibility; GRADE separates evidence quality from recommendation strength.

## D4 — Dimension score is a mechanical aggregate

No model-proposed verdict in the scoring path; the model gathers and labels, arithmetic
decides. Consequence: the override log lives at the evidence-entry level, making review
granular. **Rejected:** model renders a categorical per-dimension judgment that the
operator accepts or overrides.

## D5 — Unexamined enters at a wide prior, never excluded

"Confirmed mixed" is a narrow distribution at 0; "never examined" is a wide one at 0 —
variance separates them more sharply than exclusion did. **Rejected:** unknowns as plain
zeros over a fixed denominator — mathematically identical to `score × coverage`, it makes
unresearched companies sort low, removing the incentive to research them. Backwards.

## D6 — Scoring is a distribution; the queue sorts on P(value > bar)

Unexamined dimension → Uniform(−1, +1); with n counted entries of sample mean m →
mean `n·m/(n+1)`, variance `⅓/(n+1)`; weight-averaged, mapped to [0, 1]; Monte Carlo.

Four required properties no point estimate satisfies together: convergence at full
coverage; incentive to keep collecting when thin; honesty about unknowns; a wide-open
unknown outranks well-established mediocrity. **Worked check:** mediocre-fully-researched
(mean 0.50, P 4%) vs. strong-but-hybrid (mean 0.47, P 31%) — the mean sorts them backwards
and buries the case worth one email. Shrinkage gives corroboration a continuous reward:
one Strong entry is +0.5, not +1.0.

## D7 — Constraints are discount factors, not gates

Location, internal culture, extractive business: tolerability factors in [0, 1] with their
own uncertainty, multiplied against quality. Negotiability is **variance** (a plausibly
movable policy is wide, ~0.15–0.95); a stated non-negotiable relocation is narrow and low
(~0.02–0.10); unexamined is Uniform(0, 1).

**Why not "weight it heavily" — measured:** to drag a perfect company below neutral,
location must outweigh all seven dimensions combined (≥ 14 of 28 weight), past which
location *is* the score. No weight means "usually matters a lot, occasionally decisive."
Bonus: this deleted Company B's special-case rule (inbound contact ≈ parked) — inbound is
just wider negotiability, same arithmetic as everyone else.

**Rejected:** discrete Pass/Parked/Failed states; `1 − confidence_of_failure` multipliers;
constraints as heavily weighted additive dimensions.

## D8 — Compensation baseline is a single configured number

Poor = notably below the baseline; Mixed = roughly at it; Strong = above. No justification
branching. Check: Company A's posted band read Strong, matching the hand-researched note.
(The number itself is private config — see D23.)

## D9 — The research pass runs unattended via API

A pass with a defined start and end is what makes cost *measurable* (pivot question 3).
Instrumented: search count, tokens, wall clock. Expected end state: API-first with a
conversational escape hatch for stalled cases.

## D10 — Precision ranks; bands display

Distributions drive ranking; the UI shows bands and coarse probability, never decimals. A
single aggregator review must not produce "6.7/10" — ranking is a legitimate use of the
precision, a readout is not.

## D11 — Manual intake only in the prototype

Automated ingestion is a volume optimization; volume wasn't what the phase tested.

## D12 — Ship the high-friction review flow first

Validate the pain before optimizing it; how much friction bites is itself pivot-question-1
evidence. (Outcome, worth carrying: four distinct friction causes surfaced before a single
entry was reviewed, and all four were *design* friction, none volume friction.)

## D13 — Thin evidence outranking corroborated mediocrity is correct

Company C (nearly no evidence, wide, real upside) above Company D (corroborated negatives,
narrow, low) is the exploration property working as designed — it surfaces the cheap
high-information action ahead of a known poor fit. Pinned as a validation assertion: a
change that inverts this ordering is wrong.

## D14 — Companies are researched across multiple passes, not screened once

Follows from D6: if thin companies sort up, they get researched, so revisiting is the norm.
Consequences: passes append and target gaps; the cost metric becomes per-company-lifetime;
the queue needs "what changed since last looked"; the action vocabulary gained
`research <dimension>`. (Amended by the seed pass contract — see O6.)

## D15 — Stretch & Frontier is an inverted U keyed to personal ability

Poor at both tails: a well-trodden personal pattern (strong track record inverts the
signal), or so far beyond the edge there's no path. Strong = stretch *plus* a foundation
to climb from. Three failures of the old monotonic industry-novelty definition: no far
side; organizational novelty isn't personal stretch (Company B's greenfield
first-technical-hire role reads Mixed — being the foundation yourself is nearer
past-plateau territory than past-growth territory); a repeatedly delivered pattern scores
Poor however novel it looks from outside. Consequence: this can't be scored from posting
language alone — the pass needs the operator's extended résumé (private config) to locate
the edge. Requisition level is the strongest single signal.

## D16 — Pace folds into Stretch provisionally; expect this dimension to be learned

Slow-shipping enterprises read Mixed or lower even on hard problems — but frequency of
reps is a different mechanism from height of bar, exactly the shape that later earns its
own dimension. Logged open rather than silently absorbed. Also: learning from accumulated
decisions was deliberately *not* a prototype feature — the prototype measured whether it's
needed.

## D17 — Five pivot questions; Q5 asks what's encodable

Q5: how much of the rubric can be written down vs. learned from accumulated decisions?
Distinct from Q1 (is a proposed rating right?): two dimensions can share an override rate
with opposite causes — vague text one edit fixes, vs. judgment that doesn't reduce to text.
Instrumented by a remediation path per override (`rubric-edit` / `example-only` /
`one-off`), reported per dimension. Confound: a low override rate on an unexamined
dimension is inattention, not encodability.

## D18 — Constraints are allowed to be fatal; the bar stays put

A tolerability ceiling below the bar makes a company unreachable, accepted knowingly
("lots of fish in the sea"). The rubric's "heavy, not fatal" wording describes an intent
the arithmetic doesn't honor at this bar — a statement about `bar`, which is config, not
about the constraint. Pinned so it stays deliberate.

## D19 — "No signal" is the outcome of looking, not the state before it

Constraints default to `not_examined`; `no_signal` is a label research earns. The deciding
argument: the best seed company should be *promotable* by reasoning that its business is
generative rather than extractive — under the opposite default that research could never
be rewarded, precisely the incentive D6 exists to create. Measured cost, accepted: every P
drops ~an order of magnitude; ordering unchanged.

## D20 — Over the cliff: unreachability is analytic, not sampled

The queue splits live / over-the-cliff. Demotion requires the closed-form ceiling (every
target at the top of its support) to sit at or below the bar — "no sample cleared" and "no
sample *could*" are different claims. Fixes the real defect: P(> bar) is not a total order
(everything below the bar ties at exactly 0.00). Nothing is deleted; live section sorts on
P with E[overall] as tiebreak, and within-noise neighbors are marked.

## D21 — The queue reads a pair: standing and reach

`standing` = P(> bar) now; the only sort key. `reach` = P(> bar) under one *good* pass on
every unexamined target (one Strong entry each — +0.5 after shrinkage, the realistic best
of a pass, not a theoretical max). The pair names the band: **wide open** (low standing,
high reach), **capped** (a known fact limits upside), **no path** (over the cliff),
**contender** / **established** (reach ≈ standing — researched enough to be what it is).

Why reach: it separates capped from wide open (Company B 0.181 vs Company A 0.922, where
the analytic ceiling reads 0.95 vs 1.00 — no resolution); it collapses to standing at full
coverage; `reach − standing` is the value of undone research in sort-key units.

**Reach must never sort** — it saturates, and an empty record (0.971) out-reaches a
researched good company (0.721). **Rejected, all measured:** a pessimistic twin (0.00000
across the board — no resolution); bands on q50 (conflates bad with unknown: a
fully-researched poor company outranks Company A); bands on the ceiling; rank-relative
bands (manufactures distinctions inside Monte Carlo noise).

## D22 — The recommended action is computed; its blind spot is named

Deterministic rules, no model proposal — a divergence from a rule is evidence about the
rule; a divergence from a model is ambiguous and unreproducible. `research <target>` picks
by value of information (re-score with the target resolved favorably, take the largest
lift). **Structural blind spot, measured:** every `not_examined` constraint produces an
*identical* lift (same [0, 1] range, same clean value), so any company with k unexamined
constraints has an exact k-way VOI tie no sampling breaks. Broken by a hand-written
research-cheapness order — the one chosen number in the action path, watched for
divergence. Actions carry a `source` column (`rule`/`model`) so a proposer can be added
without migration.

## D23 — The compensation baseline leaked into the prototype repo; accepted there

By the time an untracked-config rule was written, the number was already in four committed
files and their git history, and the rubric line carrying it was quoted verbatim into
prompts. The prototype accepted the leak. **The clean build restores the original intent:
the baseline lives in untracked local config from day one and never enters a committed
file or a committed prompt log.**

## D24 — Obtainability reorders and decides; it never scores

How likely the operator is to *get* the job, as distinct from how good it is. Three tiers:
warm hiring manager (worked together; they rate the operator) / second-degree intro (a
reachable path to someone with influence) / open application (cold, against a large
field). Surfaced not from a company that didn't fit but from an *action the rules couldn't
derive* — a new door into dimension-set instability.

**Why not a dimension:** D7's additive argument. **Why not a fourth constraint — measured
and decisive:** modeled speculatively and scored — standing dropped 14–21× (a fourth
Uniform(0,1) halves the mean but takes an order of magnitude off the *tail*, and P(> bar)
lives in the tail), and `open_application`'s ceiling of 0.25 sits below the bar, so every
cold-apply company goes over the cliff — most of the real job market declared dead on
arrival. **The property that decided it:** it is the only axis an *action changes* rather
than research reveals; scoring it de-prioritizes exactly the companies where the
recommended action helps most, inverting the exploration pull. Stored append-only — a tier
change records something the operator *did*.

## D25 — Triage has two axes, and a mismatch is not a question

`status` split into `priority` (do I care) and `disposition` (what was concluded), with
**per-kind** conclusion vocabularies: corroborate → confirmed / refuted /
could-not-corroborate / not-worth-checking; interpret → reads-positive / reads-negative /
genuinely-undetermined / not-worth-deciding; mismatch → rubric-edit / needs-new-axis /
accepted-tension / one-off. Model-raised items must carry sources or they can't be
validated. The mismatch vocabulary *is* the Q2/Q5 instrument, collected at the point of
judgment. Fixed alongside: review screens show the rubric's own words for the target, so
proposal and review judge against identical text.

## D26 — One click on a plane; the raw position is kept, the bucket scores

Fit and confidence entered as one click on a 2D plane; the click is stored verbatim, then
snapped, and **only the snapped bucket ever scores** — asserted structurally in tests,
because a continuous confidence next to a multiplication is one careless commit from
confidence-as-multiplier (rejected three times). The asymmetry is the decision: **the
operator is allowed to be noisy; the system is not allowed to manufacture precision.** The
raw positions accumulate as the calibration corpus. Details that mattered: a dropdown
choice after a click clears the position (an explicit correction); the server re-snaps
rather than trusting the browser; ties snap to the *lower* anchor (never round a hesitant
click up into a stronger claim). If clicks cluster persistently between anchors, the
anchors are wrong — evidence collected rather than assumed. (First use: 12/12 via the
plane, and the clusters immediately exposed a missing confidence rung.)

## D27 — The remediation path is asked in a batch, not demanded per entry

"Does this override generalize?" is a claim about a *set* of cases; asked at entry 1 of
12 it extracts a guess, and a forced answer is worse data than a missing one. Overrides
write immediately with the path null; the debt is carried visibly and asked about
batch-wise when the overrides can be seen side by side. The risk taken (batched judgment
is further from the evidence) is noisy; the risk avoided (generalization judged with no
other case in view) is systematic.

---

## Open items (O-numbers)

- **O1** — whether the over-the-cliff section collapses by default. (Cosmetic remainder.)
- **O2** — a criteria document referenced by the brief never existed.
- **O3 — ANSWERED:** research lifts a company out of the doldrums — 302× on one pass,
  126× of it from two constraint labels alone. Thin-data suppression is fully reversible;
  no rescue mechanism needed.
- **O4** — rule vs. model for research targeting; reopened only by divergences clustering
  on the constraint tiebreak, where the arithmetic is provably indifferent.
- **O5** — action costs and the stopping rule. Key reframe: VOI should mean "would this
  change what happens," not "how far does standing move" — if the outcome is the same
  either way, the research was worthless; the stopping rule falls out free. Deliberately
  unbuilt: a cost model fitted to no data is a guess with decimal places. (One human cost
  was later measured: guessed 1.5, actual 0.36 median — guesses run 2–4× high.)
- **O6** — a pass couldn't file evidence outside its assigned gaps and had to smuggle
  material facts out as mismatches, twice, on the first real run. Defect in D14's
  implementation, not D14. Fixed in the seed pass contract: incidental filings free,
  reopening by routed nomination.
- **O7** — nothing can show an intro call paying off vs. a cover letter, because the thing
  it improves deliberately has no number (D24). Either accept forever, or give
  obtainability an expected value used *only* to compare approach actions, never touching
  standing. Blocked on real outcomes data.
- **O8** — should past decisions close future ones? The cheap honest version: retrieve and
  show precedent, never auto-close. Auto-closing blinds the override measurement exactly
  where the system is most confident, and locks thin first rulings in as law. The
  operator's measured agreement rate with shown precedent is the only evidence that could
  ever justify more.
