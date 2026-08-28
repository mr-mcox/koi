---
feature: review-ux
type: scouting
date: 2026-08-27
commit: 1038be4712dfa63ccc2b12e12141eb31267387f5
---

## What We're Doing

Operator's framing: the scoring model was the prototype's heavy lifting and is largely
resolved; what felt unpolished was *how the operator interacts with it* — reviewing and
ranking openings. The goal is an efficient use of the operator's attention, not a UI that
walks every assertion. Key requirements surfaced in conversation:

- Not all assertions are worth reviewing — leverage/VOI-style triage should apply to
  *rating*, the way it already applies to *research* targeting.
- Alignment may be needed at two granularities: individual assertions and the overall
  per-dimension rubric rating. Variance across a dimension's assertions may itself be a
  triage signal (high-weight dimension + high disagreement = surface it).
- A flywheel: recorded rulings should calibrate future automated proposals, plausibly via
  retrieved-precedent context injected into the *extraction* pass, not just the review
  screen — this may also be the mechanism that handles the `domain` dimension cleanly.
  Corrected during the session: evidence-gathering is uniform across dimensions; only
  the *rating* step (model proposes vs. operator-only) ever differs — no dimension needs
  a distinct UI mode.
- Multi-round research is normal, not an edge case: a future lightweight intake pass will
  read-only-the-posting and table the opening; deeper passes come later, triggered by
  some observable state of the opening, not a fixed schedule.
- Research state (what's been tried, what effort was spent) should be **computed from the
  saved transcript**, not stored as separate state — this also lets the system identify
  novel search targets instead of re-treading ground.
- A documented UX pattern (batch "does this override generalize?" screen, D27/W4) was
  correctly identified as retired prototype instrumentation, not a design to carry
  forward — corrected in `decisions.md` and `learnings.md` on 2026-08-27, prior to this
  scouting pass.

## Findings

- **F1** — decisions S1/S4/S5 (D6/D20/D21) — scoring core is `demonstrated`: distributions,
  analytic cliff, standing/reach pair. Settled ground; not open for this feature to
  relitigate.
- **F2** — decisions S8 (D26, `adopted`) — provenance sets variance:
  `unexamined → model_proposed → precedent_matched → ratified`, narrowing at each rung,
  never zero. This is the existing hook for "how much does a rating matter" — an
  assertion already at a narrow rung contributes less potential movement than one at a
  wide rung.
- **F3** — decisions W3 (`adopted`, from O5) — VOI is already defined for research:
  "would this change what happens," not "how far does standing move." No equivalent
  concept exists today for *rating* — this feature's central new idea is a rating-side
  sibling signal, not a new principle.
- **F4** — decisions W4 — the batched generalization-question screen (D27) is documented
  as retired prototype instrumentation, not a pattern to reproduce; `learnings.md` Q5
  carries the same note. The clean build's review UX is undecided and not obligated to
  reproduce a batch-then-ask-generalization shape.
- **F5** — decisions S7 (D4, `demonstrated`) + operator clarification — D4's wording ("the
  model never renders verdicts") is easy to over-read as "never have a verdict." Operator
  clarified the actual purpose: **the system approximates the operator's own noisy
  judgment**, as if they had unlimited time and perfect information — not a verdict-free
  system, a *guess-at-their-verdict* system, built to respect their actual time and to get
  better at guessing over time. D4's wall is narrower than it first reads: the *model*
  (the LLM doing extraction) doesn't get to render the verdict; a mechanical/computed
  aggregation step rendering an approximation of the operator's verdict is exactly the
  product, not a wall violation. This reframes F6 below — no tension with D4 remains.
- **F6** [x] — closed by operator → §F6 resolution below. A dimension-level Ruling is
  **an independent object**, not a derived/retroactive state on assertions: "given all of
  the underlying assertions & rulings, what's the overall disposition for this
  opportunity on this dimension." Assertions underneath keep whatever provenance they
  already carry; the dimension-level Ruling sits above them as its own record. Operator
  also flagged the aggregation is **not** an arithmetic mean — "squish," a non-linear
  judgment call, not a formula computed off the assertion set. Open remainder: *how* the
  squish gets captured (a scalar? a rationale? both?) is a bearing-time interaction
  question, not a domain-model one.
- **F7** — operator — research state should be *computed*, not stored: "if we effectively
  save the transcript, we can resume state at any point and also compute turns... help
  identify additional/novel search targets rather than retreading same ground."
- **F8** — `src/screen/intake/transcript_io.py:1-6` — the transcript wrapper is already
  append-only by construction (`TranscriptLockedError`, no truncation path), one JSON
  event per line, replayable via `read_transcript`. This is the substrate F7 depends on;
  it already exists and needs no schema change to serve as a replay source.
- **F9** — `src/screen/loop/state.py:16-39` — `LoopState` already treats `visited_urls`,
  `prior_queries`, `searches_used`, and `tokens_used` as per-pass working values, not
  independently persisted facts — consistent with computing them fresh from a transcript
  replay rather than carrying a separate persisted counter forward.
- **F10** — `data/coinbase/openings/.../transcript.jsonl:1` — real transcript shape
  confirmed: `{"ts", "tool", "request", "response"}` per line, one `tavily_extract` call
  logged for the coinbase pass. Sufficient detail to replay "what was searched/fetched" at
  minimum; whether it's sufficient to derive "which targets got no signal despite being
  searched" is unverified — this one pass didn't exercise search. Headway's data predates
  the current pipeline (operator: "based on an old version of code") and is not a reliable
  sample of current transcript shape — don't infer format from it.
- **F11** [ ] — does the existing transcript log enough to distinguish, per target,
  "searched, found nothing" from "never attempted"? Both `visited_urls`/`prior_queries`
  and the assigned-gaps concept (domain-model.md's `ResearchPass` contract — "budget is
  spent only on assigned gaps") suggest yes, but no code path currently reads a transcript
  back out this way; unverified against a pass that actually exhausted search budget on a
  target and found nothing.
- **F12** — domain-model.md (`ResearchPass` contract) — passes already carry: assigned
  gaps, budget instrumentation, "incidental evidence filed free against any target,
  including settled ones," and a defined nomination-for-reopening mechanism (routed, not
  auto-acted). An operator's free-text lead ("check for layoffs") is naturally the same
  *kind* of input as a pass's own gap-detection or reopening nomination — one nomination
  mechanism, two sources (pass-detected, operator-flagged), rather than a second pathway.
  No code implements nomination-routing yet; this is a domain-model-level fit, not a
  verified implementation.
- **F13** — decisions S2 (D7, `demonstrated`) + cross-cutting learnings finding —
  constraints (not dimensions) did the discriminating in the one real pass (302× standing
  lift, 126× from two constraint labels). This is direct evidence that a rating-VOI signal
  (F3's proposed sibling) should weight constraints heavily when ranking what's worth the
  operator's click — matches the operator's own worked example in conversation
  (Coinbase's `location` assertion being higher-leverage than `agentic`/`stretch`).
- **F14** — decisions E2 (D3, `demonstrated`) — fit and provenance/confidence are separate
  axes, never blended. Any triage/VOI display must keep this distinction visible — a
  "leverage score" surfaced to the operator is itself a derived, display-only number and
  must not become a new blended field feeding the Scorer (would reopen the
  confidence-as-multiplier wall, rejected three times).
- **F15** — open-questions.md #12 — `PrecedentLookup` is framed as gated behind corpus
  volume and a real consumer (most likely comparing a new opening's `domain` evidence
  against ruled precedent). The flywheel idea from this session (RAG context injected into
  *extraction*, not just the review screen) is a candidate early, cheap version of this —
  worth a note in open-questions.md if pursued, since #12 as written expects this to wait.
  Not yet a resolved finding: whether extraction-time injection is buildable before
  meaningful corpus volume exists (only 2 seed openings today, one with zero assertions).
- **F16** — data — `data/coinbase/openings/.../assertions.jsonl` has 7 assertions, all
  `model_proposed`, none ratified yet, from the current pipeline (F10 caveat: this is the
  representative sample, not Headway). Headway (`data/headway/openings/staff-infrastructure-engineer-b7a254/`)
  predates the current pipeline and has no `assertions.jsonl` for that reason — it does
  **not** confirm "shallow pass, table it" is a state the current system produces; that
  remains a forecast about a future lightweight-intake adapter, not something demonstrated
  in today's data.
- **F17** — `src/screen/types.py:69-95` — `Target` is a closed `Literal` (Wall 3); the
  `_SCORING_TARGETS` / `_CONSTRAINT_TARGETS` / `_NON_SCORING_TARGETS` lists are fixed at
  the type level. Any new derived concept (rating-VOI, dimension-level Ruling, computed
  research state) needs to be additive to this closed set or live entirely outside
  `Assertion`/`Target` — it cannot loosen the Literal without a wall-level decision.
- **F18** — domain-model.md §Judgment/Ruling — `Ruling` today is described at "the
  operator's review event: proposed vs. final labels, the raw click, remediation path."
  Nothing in the current domain model names the *granularity* (assertion vs. dimension)
  explicitly — it's implicitly assertion-level throughout (D26's click is per-assertion).
  F6's open question is really asking whether `Ruling` needs a `scope` field or a sibling
  type.

## Not Yet Settled (carried into bearing discussion)

- Whether rating-VOI is computed by the existing Scorer (extended) or a new adjacent
  service — no finding pins this; it's an implementation shape decision.
- F6/F18 — dimension-level Ruling's relationship to assertion-level provenance.
- F11 — whether the transcript format as currently logged (F10) actually carries enough
  to compute "no signal despite searching" per target, or needs a small additive change
  (e.g., logging which target a search was assigned to explore) to make that computable
  after the fact.

## Frontend shape (added mid-stream)

F19–F24 fed `../review-shell/bearing.md` (the delivery-shell slice of this feature) —
see that bearing's Approach/Agreed for where each landed.

- **F19** — operator — the queue is the central view but not the only one; a separate
  surface (sidebar or distinct screen) for presenting items to rate is expected, and the
  domain model may surface further views beyond these two.
- **F20** — operator — the concrete bar for "modern, not janky": submitting a rating
  re-sorts the queue without a full page reload. This is the load-bearing UX criterion,
  not a general aesthetic preference.
- **F21** — `src/screen/api/routes.py:1-24` — routes already separate domain computation
  (`score_opening`, `assertions_for_opening`) from response shaping (`_to_response`); an
  HTML-rendering route calls the same domain functions and shapes a template instead of a
  `ScoreResponse`, so adding server-rendered views doesn't touch the domain layer.
- **F22** — operator — the regret being avoided is asymmetric: an HTMX/server-rendered UI
  carries no client-side API contract to keep in sync with a still-moving domain model
  (Ruling granularity, F6/F18); a typed Svelte+API split would require committing to that
  contract now. Reversal cost favors starting server-rendered.
- **F23** — operator — client-side-only interactions (keyboard-driven triage, drag-reorder,
  undo-before-commit, live cross-panel state) are not on the near-term roadmap; explicitly
  out of scope for this bearing rather than a hedge to design around.
- **F24** — `job-screener-prototype/templates/*.html`, `static/app.css` — prototype was
  Jinja2 server-rendered with hand-written CSS (no HTMX, no JS framework); band/fit are the
  only elements styled with semantic intent (`.chip.band-*`, `.fit-*`). Confirms this
  shape's viability for the same queue/company-review content and gives a starting visual
  vocabulary, not a UX pattern to reproduce wholesale (per W4, don't carry prototype UX
  forward uncritically).
