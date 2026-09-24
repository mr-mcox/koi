---
feature: rubric-peer-stretch-revision
type: scouting
date: 2026-09-24
commit: 531ee63
---

## What We're Doing

Operator: "peer isn't holding its weight — evaluating who I'd work with needs interview/
conversation history, not web search, so drop it entirely." And: "stretch should be
recalibrated — I'm using it in my head as 'is this a way I want to continue growing in,'
which isn't what the rubric currently represents. Strong = a genuine mixture of designing
solutions with LLMs (AI engineering) and standard ML (deep learning especially). Mixed =
things I've done before but am less excited about — data engineering, analytics
engineering, dev ops, backend engineering. Poor = front end engineering, embedded systems —
no depth to draw from, all energy goes to catching up on toolset concerns." Rename is fine
so downstream data re-fetches; backfill from JDs where possible.

Operator, second pass: existing `stretch` evidence isn't informative — staff-titled +
in-range-comp postings essentially never come with an off-level signal in this corpus (→ F9).
`stretch`(new) differs from `domain`: "a recommendation system for ad tech is high on
stretch(new), low on domain; backend engineering at Splice is mixed on stretch(new), high on
domain." `agentic` is about tooling specifically — Claude/Cursor use is Mixed; evidence of
varied tooling experimentation, ~80% agent-authored code, and a generous token budget is
Strong. Mostly JD-legible, but not entirely: an aspirational "please do ML and AI" JD with no
supporting evidence is a red flag (data probably isn't in order, a year could go to pipeline
setup); a blog/conference-talk trail discussing the work lends credibility. Operator also
asked: does the LLM scorer need to know how likely the operator is to override.

## Findings

- **F1** — `rubric.yaml:126-157` — current `peer` definition scores public-evidence
  specificity (named senior hires, engineering-blog depth, hiring-bar detail), weight 2.
- **F2** — decisions R5 (`docs/architecture/decisions.md:266`) — `demonstrated`: 10/10 generic
  "we do code reviews" claims landed Mixed and never co-occurred with Strong; Strong cases
  were categorically distinct (named senior hire, substantive blog, hiring-bar detail,
  concrete practice+outcome). This calibration is the thing being discarded if `peer` is
  dropped outright, not folded elsewhere.
- **F3** — operator — `peer` should be dropped entirely, not converted to a manual/operator-only
  dimension like `domain`. It is "not useful for screening" — no request to preserve it as a
  post-interview signal.
- **F4** — decisions OQ16 (`docs/architecture/open-questions.md:174-187`) — "software is core
  to strategy" talent-density half was explicitly folded into `peer` (R5). Dropping `peer`
  reopens this half with no home; OQ16 itself is unresolved and untouched by this change.
- **F5** — `rubric.yaml:36-83` — current `stretch`: ability-distance from operator's current
  level, inverted-U, weight 3, anchored on requisition level/seniority vs. résumé. `notes`
  field: "the least trustworthy dimension in the rubric... expect overrides."
- **F6** — decisions R1 (`docs/architecture/decisions.md:241-247`) — `demonstrated`: this
  ability-distance framing, seniority as strongest single signal, took two calibration
  rounds. R2 folds "organizational pace" into `stretch` as `provisional` (watch it) —
  unaffected by this change since it's a distinct mechanism.
- **F7** — domain-model.md:54,255,261 — `stretch` is a role-level (Opening) dimension; "whether
  organizational pace earns its own dimension" is a named volatility area, folded into
  `stretch` provisionally — this bearing does not touch that fold.
- **F8** ⚠ — `rubric.yaml:36-55` — `stretch`'s current definition is explicitly *not*
  domain/craft-indexed: "Ability-indexed only, not shape-indexed... A protocol-mastery role
  can be stretch-Strong while schematic-Poor." The operator's new definition (LLM+ML vs.
  frontend/embedded) is a discipline-preference axis, not an ability-distance axis — this is
  a different dimension in substance, not a recalibration, and directly supersedes R1's
  model. `schematic` (shape-of-work: originate structure vs. depth-in-a-fixed-frame) is
  independent of both and is not a candidate home for the ability-distance signal.
- **F9** — `data/live/screen.db`, `assertions` table (queried read-only) — target=`stretch`:
  89 Strong / 3 Mixed / 0 Poor across 92 assertions in the live corpus; nearly every Strong
  chunk is a bare seniority/title match ("Staff", "Senior/Staff", years-of-experience)
  regardless of domain (ad tech, backend, data platform, ML all score Strong alike).
  Corroborates operator's claim (in-conversation) that the qualified-but-wrong-level case
  essentially doesn't appear in this corpus — current `stretch` evidence is low-information
  in practice, not just in theory.
- **F10** — `data/live/screen.db` — target=`agentic`: 77 Strong / 28 Mixed / 5 Poor. Strong
  chunks are heterogeneous: some are single tool-mentions ("prompt engineering," "RAG
  patterns"), others are substantive ("Minions are Stripe's homegrown coding agents...
  thousand PRs merged each week"). Current `fit_anchors` (`rubric.yaml:203-222`) already
  roughly matches the operator's Poor/Mixed/Strong distinctions (Copilot-tier / individual
  use / real org investment) — the operator's clarifying examples in this session (Claude
  vs. Cursor = Mixed; 80% agent-authored + token budget = Strong) sharpen but do not
  contradict the existing anchors.
- **F11** — architecture README girder — "Rubric text is load-bearing and versioned — the
  extraction prompt is generated from `rubric.yaml`, never freeform" →
  `tests/test_rubric.py`. Any wording change flows automatically into research prompts; no
  separate prompt file to sync.
- **F12** — `src/screen/types.py:77-89,99-112` — `Target` is a closed `Literal` list plus
  `_SCORING_TARGETS`; `peer` appears in both, `stretch` slug appears in both. A rename or
  removal requires editing this file (Wall 3) in addition to `rubric.yaml`. OQ13
  (`open-questions.md:140-150`) already flags this hand-sync as a recurring gap; this would
  be a second instance if it hits the same friction (drop `peer` = removal in 3 places:
  `rubric.yaml`, `types.py` Literal, `types.py` `_SCORING_TARGETS`; also `extract.baml`
  schema per domain-model.md's Assertion note at `rubric.yaml:9`).
- **F13** — `docs/architecture/decisions.md` R4 (line 260) and domain-model.md Rubric section
  — "every rubric change carries a reason; the change log is the dimension-stability
  instrument." Both changes need a new `decisions.md` entry (R-number), not just a diff.
- **F14** — operator — asked whether the scoring LLM needs to know override-likelihood.
  Nothing in `rubric.yaml` or the Scorer model (domain-model.md §Scorer) carries a per-target
  override-probability signal into extraction; `provenance` (model_proposed →
  precedent_matched → ratified) is the only mechanism that widens/narrows a distribution, and
  it's set by the Ruling pipeline post-hoc, not by the extraction prompt. `rubric.yaml`'s
  `notes:` field on `stretch` (F5, "expect overrides... least trustworthy") is *not* consumed
  by the scorer or the extraction schema today — it is a comment for future readers/operator,
  not a value that changes variance. [!] whether it should become one → Recalibrate When.
- **F15** — no `docs/CURRENT.md` tip existed at session start (empty file); this is the first
  bearing under this workflow for the rubric-revision task.
- **F16** — operator — no research pass should be *required* for the new `stretch`; mostly
  JD-legible from title/description, but corroborating evidence (blog posts, conference
  talks, discussion of ML/AI work actually shipped) raises confidence, and its *absence*
  under an aspirational "we do AI/ML" JD is itself a negative signal (immature data
  infrastructure risk). This means `look_for` needs both a cheap JD-only path and a
  higher-value corroboration path, unlike `domain` (OQ12) which was excluded from
  gap-detection entirely because research can't move it at all.
- **F17** — open-questions.md OQ12 (`open-questions.md:113-138`) — precedent for excluding a
  dimension from research gap-detection (`domain`) because the planner burned budget chasing
  an unmovable target. Relevant contrast for F16: new `stretch` is *not* proposed for that
  treatment — it's JD-legible by default but researchable for the corroboration case, so it
  should stay in normal gap-detection, unlike `domain`.
