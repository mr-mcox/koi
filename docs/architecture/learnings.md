---
name: learnings
type: learnings
date: 2026-08-21
provenance: one full prototype cycle — one research pass (Company A), twelve entries, one review sitting; Company pseudonyms defined in prototype-decisions.md
companions: prototype-decisions.md, open-questions.md
---
# Learnings — Clean Build Seed
Distilled 2026-08-21. Answers to the prototype's five pivot questions, with each claim
carrying its own evidence grade — because treating a one-sitting read as load-bearing is
the failure mode this project rejects on sight. Company pseudonyms (A–D) are defined in
`prototype-decisions.md`.

**Grades:**
- `demonstrated` — numeric, reproduced, or repeatedly observed; safe to build on.
- `measured once` — real data, n≈1 (one company / one run / one sitting); build on it, but
  cheap to falsify and worth re-checking early in the clean build.
- `suggestive` — a pattern below significance; watch, don't build on.
- `untested` — asserted by the model design, never exercised.

The prototype ran exactly one full cycle: one research pass (Company A), twelve proposed
entries, all twelve reviewed in one sitting by one reviewer. Everything below inherits
that caveat unless graded `demonstrated`.

---

## Q1 — Does automated classification track the operator's judgment?

**Fit tracks; confidence had a systematic offset; and the offset barely moved the answer.**

- `measured once` — 12 entries reviewed in 9.1 minutes, median 21.5s. **7 overrides in 12
  entries (58%), but the model's proposal and the operator's ratified version are the same
  company**: standing moved 0.94253 → 0.95542, band and depth unchanged. Most disagreement
  lived in a channel the arithmetic discarded.
- `measured once` — fit overrides were 3/12 and non-directional (+1, −1, +1).
- `suggestive` (sign test p ≈ 0.13) — every confidence override moved **upward**: the model
  is more cautious about its own sourcing than the operator is. Exactly the shape a single
  line in the research prompt could correct.
- `demonstrated` — the old confidence ladder was missing a rung: six of twelve raw plane
  clicks landed in 0.55–0.90, above Medium and below High, and three of seven overrides
  were arithmetically inert because Medium and High scored identically. This measurement is
  what motivated provenance-as-variance (seed DECISIONS S8).
- `demonstrated` — **review friction was design friction, not volume friction.** Four
  distinct causes bit before a single entry was reviewed (comprehension: "I'm unclear on
  what to do with the 12"; source granularity: scrolling review pages "untenable"; a block
  that silently discarded the submitted answer; a block that fired on nearly every plane
  click). All four were fixed same-day; none was the anticipated tedium. The predicted
  volume friction never materialized at n=12.
- `demonstrated` — attribution can be audited and came back clean: 54 URLs returned, 9
  cited, all real, all company-specific; the model guarded a confusable-name trap unprompted
  (an unrelated firm sharing Company A's name) and declined to dress up generic articles as
  evidence for its thinnest dimension. (This verifies attribution, not accuracy — accuracy
  is what review is for.)

## Q2 — Are the dimensions stable?

**The categories held; the definitions and the schema around them did not.**

- `measured once` — the operator, after triaging run 1's model-raised items: "nothing jumps
  out as having improper dimensions." The work needed is `rubric-edit`, not
  `needs-new-axis`.
- `demonstrated` — **new axes arrive through doors a free-text "doesn't fit" hatch never
  watches.** Both post-build axes came from elsewhere: pace from a pattern across
  employers, obtainability from an *action the rules couldn't produce*. A third door:
  a definition can be the wrong *shape* while its category fits fine (Stretch was
  monotonic; it's an inverted U — a full inversion on the heaviest dimension). The clean
  build's stability instrument is the rubric change log plus routed feedback, watching all
  three doors.
- `demonstrated` — schema gaps masquerade as rubric gaps. Of eight open "mismatches," only
  ~3 were rubric questions; the rest were a missing data field (`source_date`), suppressed
  evidence (the pass-contract defect), and an adjudication request. The escape hatch worked;
  triaging everything in it as a rubric question did not.

## Q3 — Is per-company evidence-gathering cost bounded?

**Bounded because we bound it; dollars are not the constraint.**

- `measured once` — one pass: 12 searches (exactly the cap, and the cap bit — two named
  gaps went unresearched), 157k tokens in / 12.5k out, ~$1.10, 215 seconds. Input tokens
  scale with search count (the server-side loop re-feeds context), so the search cap is the
  spend dial too.
- `demonstrated` (by design contact with reality) — the real metric is **passes per
  decision**, not cost per pass. A cheap first pass needing six follow-ups is not bounded.
  Zero data on this yet.
- `measured once` — the one human cost measured: review guessed at 1.5, measured 0.36
  median — guesses run 2–4× high. Resolution: costs are configured numbers the operator
  owns, not measurements (seed DECISIONS W3).

## Q4 — Does a useful "next best action" fall out?

**Answered by dissolution.** The deterministic recommender reproduced 3 of 4 of the
operator's stated reads (`measured once`), and its one miss was a missing *state*, not a
missing rule (unscreenable — no rule can recommend an action for a state the schema
doesn't have, `demonstrated`). But the durable finding is that directive recommendations
aren't the product: the product is ranking + routing + collected affordances. Two of the
brief's five actions were underivable because the data model lacked an axis
(obtainability) — a missing action revealing a missing axis, which is a Q2 door in its own
right.

## Q5 — Encode up front, or learn by calibration?

**Early signal: the rubric is near its encodable limit; further accuracy comes from
accumulated cases.**

- `measured once`, with a structural caveat — remediation paths on the seven overrides:
  `example-only` 7 of 7, zero `rubric-edit`, across four different dimensions. Read
  literally, no gap was closable by better wording — the argument for retrieve-and-show
  precedent and against further rubric-polishing. Caveat recorded before the result: all
  seven were answered in one batch in one sitting, and unanimity is what an anchoring
  artifact looks like. The next company's overrides, in a separate sitting, either
  replicate this or they don't.
- `measured once` — the prediction "Stretch will need learned calibration" was right and
  too narrow (agentic, peer, and internal-culture overrides were also example-only).
- `demonstrated` — the confound stands: a low override rate on an unexamined dimension is
  evidence of inattention, not encodability. Most dimensions remain barely exercised.

## Cross-cutting

- `demonstrated` — **constraints, not dimensions, do the discriminating.** Of Company A's
  302× standing lift from one pass, 126× came from resolving two constraint labels;
  the nine dimension entries contributed 2.4×. Research provably lifts a company out of
  the doldrums — thin-data suppression is fully reversible, not a trap.
- `demonstrated` — the model's prose can be right while its data is wrong (it *wrote*
  "same-organization corroboration, treated as non-independent" and then filed the row as
  independent because the schema had nowhere else to put a second URL). Schema shapes
  honesty; transcripts are the only place this class of bug is visible.
- `demonstrated` — a deliberate block that silently discards the user's answer is
  indistinguishable from a broken form. Blocks must preserve submitted state.
- `untested` — convergence at full coverage; the behavior of most dimensions under real
  evidence; the urgency mechanism (no real `source_date` ever entered); batch ranking
  behavior with more than a handful of companies. The steel thread's batching phase is
  aimed at the last of these.
