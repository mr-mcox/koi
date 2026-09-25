---
feature: rubric-mission-trajectory-split
type: scouting
date: 2026-09-24
commit: 583562a
---

## What We're Doing

Operator: noticing that `mission` and `extractive_business` are redundant. Also, `mission`
carries language about non-performative AI use that "feels a bit off." Their actual mental
segmentation: `mission` = "if this company were successful, would I want to be a part of
it," and `trajectory` = "are they likely to be successful." The AI-authenticity question is
a small part of the latter (whether the company's stated strategy is real) — possibly not
worth its own callout at all.

## Findings

- **F1** — `rubric.yaml:131-150` — `mission` (weight 2) definition: "Does the business win
  when the customer wins, or by extracting from them — plus whether any 'AI-powered' claim
  is real product leverage or investor decoration." Fit anchors score customer-extraction
  *and* AI-authenticity as one blended axis (Poor anchor covers both "extracting from the
  customer" *or* "AI claims read as decoration").
- **F2** — `rubric.yaml:257-279` — `extractive_business` (weight 4) definition: "Extreme or
  obvious cases where the core business model extracts value from users... Anything less
  obvious flows into `mission`, which is built for nuanced middle ground; this dimension is
  for clear-cut anchor cases only." Explicitly defined as the same axis as `mission`'s
  customer-extraction half, split by confidence/obviousness rather than by subject matter.
- **F3** — `rubric.yaml:108-129` — `trajectory` (weight 2) definition: "is the company's
  trajectory actually healthy, AND would the operator's specific work be load-bearing to
  it." No AI-authenticity language present here today.
- **F4** — operator — the intended segmentation is subject-matter, not confidence-tier:
  `mission` = "would I want to be part of this if it succeeds" (values/extraction
  question); `trajectory` = "will it succeed" (health/strategy-reality question). Under
  this framing `extractive_business` and `mission`'s extraction half are the *same*
  question asked twice at two confidence bands, which is the redundancy being named —
  distinct from `trajectory`, which is a different question entirely.
- **F5** — operator — AI-authenticity ("is 'AI-powered' real or decoration") sits under
  *trajectory* ("will it succeed") in the operator's mental model, not under mission
  (values). It may be too minor to warrant a dedicated callout in fit_anchors at all,
  rather than needing a new home.
- **F6** — decisions S12 (`decisions.md:160-174`) — `extractive_business` used to be a
  `ConstraintRange`/discrete-situation-label mechanism; S12 retired that machinery and made
  it "an ordinary `rubric.yaml` dimension, scored by the same shrinkage math as every
  other dimension." Nothing in S12 addresses the confidence-tier split *within* the
  extraction question (that split predates S12 and is untouched by it) — S12 is about
  mechanism (constraint vs. weighted dimension), not about whether two dimensions should
  encode the same axis at two confidence bands.
- **F7** — decisions D19 (`prototype-decisions.md:166-172`) — "no signal" as the *outcome*
  of looking, not the default, was the deciding argument for `extractive_business`'s
  current Poor/Mixed/Strong shape (a company should be *promotable* to Strong by reasoning
  it's generative, not stuck at Mixed by default). This shape argument is independent of
  which dimension carries it — it would need to survive intact if `extractive_business`
  merges into `mission` or is redefined.
- **F8** — `rubric.yaml` weights — `mission`: 2, `extractive_business`: 4, of 31 total.
  Any merge/resegmentation changes the weighted mixture the extraction question gets
  relative to the rest of the rubric; this is a number the operator owns, not one to infer.
- **F9** — architecture E4 (`decisions.md:220-224`) — evidence for `mission`/`trajectory`/
  `internal_culture`/`extractive_business` all attaches at the Company level, not Opening.
  A resegmentation here doesn't cross that boundary either way.
- **F10** — architecture girder — rubric text is load-bearing and versioned (R4); any
  wording change needs a `decisions.md` R-entry recording what it supersedes, same pattern
  as R7/R8 in the just-finished `peer`/`stretch` work.
- **F11** — `domain-model.md:44` — the dimension list there ("mission fit, trajectory &
  leverage, peer caliber, agentic/AI engineering...") is already stale post-`peer`-removal
  (R7) and doesn't mention `extractive_business` or `craft_direction`. Pre-existing drift,
  not caused by this change, but a resegmentation would add to what needs fixing there.
- **F12** ⚠ — `rubric.yaml:25` — a top-of-file comment already asserts `location`,
  `internal_culture`, and `extractive_business` "carry no special [constraint] treatment"
  (S12's point). If `extractive_business` is dropped/merged, this comment's slug list needs
  updating too, or it silently references a retired dimension.
- **F13** [x] — operator: drop `extractive_business` entirely, like `stretch` was dropped
  (not folded) in `redefine-stretch.md` — `mission` absorbs the full extraction question at
  one confidence-agnostic band → bearing Approach, Agreed.
- **F14** [x] — operator: fold AI-authenticity into `trajectory`'s fit_anchors as a
  hype-vs-defensible-strategy signal, not into `agentic` (tooling quality) or `mission`
  (values) → bearing Approach, Agreed.
- **F15** [x] — operator: `mission` weight stays at 2. No new weight is picked up by
  `trajectory` for absorbing the AI-authenticity sub-signal — weight 2 unchanged. If
  `mission` scores poorly but opportunity still ranks high in practice, that's deferred,
  not solved now → bearing Not Doing.
- **F16** — decisions R9 (`decisions.md:331-348`) — the read-boundary mapper
  (`src/screen/store/mappers.py:32-49`) already validates every stored `target` against the
  live `Target` Literal and drops/warns on anything retired, generically, per-row. Removing
  `extractive_business` from `Target` is sufficient to get the "filter out on read" behavior
  the operator asked for — no new mechanism needed, same as `peer`'s removal used.
- **F17** — `src/screen/types.py:87,108` — `extractive_business` appears in both
  `_SCORING_TARGETS` and the `Target` Literal; removal touches both, mirroring `drop-peer.md`.
- **F18** — `src/screen/baml_src/extract.baml:98`, `research.baml:116,138,162,185,206,231,
  235,253,276` — `extractive_business` is named in rubric-summary prompt strings and one
  test's `primary_target` fixture; these need updating for the removal to be complete,
  same category of edit as `drop-peer.md`'s BAML step.
- **F19** — `tests/test_score_loader.py:10`, `tests/test_types.py:201`,
  `tests/test_scorer.py:53`, `tests/test_research_trace_replay.py:285`,
  `tests/intake/test_identify_research_trace.py:231` — five tests assert or fixture
  `extractive_business` as a live target; all need updating in the same change, consistent
  with `drop-peer.md`'s `check.py`-surfaces-it approach.
- **F20** — `rubric.yaml:25` comment (→ F12) lists `location`, `internal_culture`,
  `extractive_business` as the no-special-treatment slugs; needs its list updated to drop
  `extractive_business` as part of this change, not left stale like `domain-model.md:44`
  (F11) already is.
