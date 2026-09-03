---
feature: research-resumability
type: scouting
date: 2026-09-02
commit: e0b5661
parent: ./bearing.md
---

## What We're Doing

Operator, live: "Just tried and it still stopped a little early, but at least did a little
more research." Follow-on from dropping the "≥1 assertion per target" stop clause — the
narrow unblock landed, but the planner still has no notion of which targets are *actually*
settled versus which need more digging. Operator's own framing from the prior session:

"Ideally, we keep digging where there's still a bunch of uncertainty (as defined by me via
dimension rulings). Salary range may be pretty well settled but peer caliber may take more
digging. Or I want to dig into business model or company trajectory. I'm sort of inclined
to pass to the prompt where our biggest uncertainties are and have it use that as a guide
for what to search for next (with knowledge of prior searches to help it not repeat
itself). And then it should just keep generating more searches and fetches until it
reaches budget."

## Findings

- **F1** — `docs/architecture/open-questions.md` #4 ("Research targeting: rule vs. model")
  — this is a narrower instance of a question the architecture already tracks as
  deliberately open: "the arithmetic is provably indifferent between unexamined
  [targets]... a hand-written cheapness order breaks ties today," settled by "the operator
  batch-authorizing a *different* target than the rule ranked first." This scout is that
  question coming due for the research-pass planner specifically (as opposed to the
  reconciliation UI it was originally scoped around).
- **F2** — `src/screen/types.py:180-186` (`DimensionRuling`) — `mean` (operator's stated
  fit, [-1,1]) and `settledness` (operator's stated conviction, [0,1], 0=loose opinion,
  1=strongest confidence) already exist as exactly the uncertainty signal the operator is
  asking for. Nothing needs to be invented; `settledness` low = dig here, `settledness`
  high = leave it. No ruling recorded for a target is the most uncertain case of all —
  more uncertain than a low-but-nonzero settledness rating.
- **F3** — `src/screen/store/repo.py:185` (`dimension_rulings_for_opening`) — already reads
  every `DimensionRuling` row for an opening. The read path exists; nothing new needed on
  the storage side.
- **F4** — `src/screen/intake/cli.py` — grep for `DimensionRuling`/`dimension_rulings_for_
  opening` in this file returns nothing. `LoopState` is built in three places
  (`_identify_research_trace`, `_resume_opening`, — both funnel into `_run_dispatch`) and
  none of them touch operator rulings today. This is the wiring gap: settledness data
  exists and is queryable, but never reaches the research loop.
- **F5** — `src/screen/research/state.py:20-42` (`LoopState`) — has no field for
  per-target settledness or ruling data at all today. Adding one is a new field on a
  frozen, `extra="forbid"` Pydantic model — additive, not a signature break for existing
  callers that don't populate it (a default is required or every call site breaks; needs
  a decision either way).
- **F6** — `src/screen/baml_src/research.baml:36-42` (`DecidePlan` signature) — takes
  `targets_covered` (comma list) and `coverage_summary` ("stretch(2), peer(1)") as its only
  per-target signals, both counts. Neither is aware of `mean`/`settledness`. A third
  argument (something like `target_uncertainty` — e.g. "peer(unrated), compensation(0.8
  settled), trajectory(0.2 settled)") would sit alongside these, not replace them —
  coverage (has evidence at all) and settledness (is the evidence corroborated enough) are
  different questions.
- **F7** — `src/screen/baml_src/research.baml:52` — this session's narrow unblock changed
  the stop clause to "every rubric target already has multiple assertions from independent
  sources and no unexplored, relevant lead remains" — still count-based (multiple ≥ 2),
  still blind to settledness. Operator's live report ("stopped a little early") is this
  clause firing on a target that has 2+ assertions but low settledness — exactly the gap
  F2 names.
- **F8** — `src/screen/research/baml_planner.py:39-63` (`last_context_text`) — already
  renders the last search/fetch result to prose for the prompt; `LoopState.prior_queries`
  is already threaded into the dispatcher and (per the operator's "with knowledge of prior
  searches to help it not repeat itself") the prompt already says "Avoid queries already in
  prior_queries" (research.baml:73). The "don't repeat yourself" half of the operator's ask
  is already built — only the "know where uncertainty is" half is missing.
- **F9** — `docs/architecture/decisions.md` S2/S8 (confidence-as-multiplier rejected three
  times) + `src/screen/score/triage.py:1-8` header comment — precedent exists for *reading*
  settledness to rank where attention should go (`triage.py`'s `swing` — "how much would
  rating this move standing") without letting it *reweight* the Scorer's math. A
  settledness-guided research planner is the same shape: settledness informs *where to
  look next*, never *how much an assertion counts*. Any Approach here should hold that
  line explicitly, since this is the exact failure mode the girder guards against.
- **F10** — `docs/features/review-ux/attention-allocation-scouting.md` F8/F11 (operator,
  prior session) — "research-pass bandit: which opening should the agent spend its next
  research pass on" is explicitly named as a *separate, cross-opening* bandit from what
  this scout addresses. This scout is *within one already-selected opening* ("which target
  to dig into next"), the bandit is *across openings* ("which opening gets the next pass
  at all"). Related — both eventually read the same per-target leverage/settledness
  signal — but distinct action spaces, confirmed by that scout's own F11.
- **F11** — bearing.md Recalibrate When (this feature, prior session) — "The planner's
  coverage-based stop keeps firing before the turn budget is exhausted... the coverage
  stop and budget stop are pulling in different directions and the stop rule needs
  renegotiation." This scout is that recalibration trigger having fired, now being
  followed up per the workflow's own rule (escalate on anything in Recalibrate When).
- **F12** — operator, this session — "then it should just keep generating more searches
  and fetches until it reaches budget" — a lean toward dropping the coverage-based stop
  clause entirely (not just reweighting it), leaving turn-budget exhaustion and "nothing
  further to research with the available tools" as the only stop conditions. Explicitly
  framed as "or am I overcomplicating" — the operator is not fully committed to this, it's
  a lean.
- **F13** [x] — closed by operator, this session: "Just dropping that stop condition in the
  prompt for now would be fine to unblock" — narrow fix landed same session (removed the
  "≥1 assertion" clause from `research.baml`'s stop condition, regenerated the BAML client;
  `docs/features/research-resumability/bearing.md` unaffected, no Done When criterion
  named this clause). This scout is the *next* increment, not a redo of that one.
- **F14** [!] — the operator's live report ("still stopped a little early, but at least
  did a little more research") is one anecdotal run, not an instrumented one. Open
  question #11 ("How many passes does a decision take?... settled by per-company lifetime
  instrumentation") applies here too: this scout's Approach should not tune a threshold
  off one observation. → Recalibrate When candidate: needs a few more real runs before
  concluding the settledness signal (once built) is itself well-calibrated.
- **F15** — `src/screen/score/loader.py` / `scoring.yaml` (research-resumability bearing,
  prior session, Approach) — every operator-facing dial in this codebase lives in
  `scoring.yaml`, named and owned, never a code literal. If this scout introduces a
  settledness threshold (e.g. "stop digging once settledness > X"), it is a `scoring.yaml`
  dial, not a hardcoded number in the prompt or dispatcher — consistent with this
  bearing's own `research_turns_budget` precedent.
- **F16** — operator, this session — rejects model-generated `DimensionRuling`s outright:
  "we don't want to have the models come up with dimension rulings." `DimensionRuling`
  stays operator-only, full stop — not a case-by-case call, a hard boundary.
- **F17** — `src/screen/score/scorer.py:41-72` (`TargetStats`, `_target_stats`) — the
  uncertainty signal the operator asked about already exists and needs no new entity:
  `half_width = 1.0 / sqrt(n+1)` where `n` is the provenance-weighted assertion count for
  a target, computed purely from `Assertion` rows (no `DimensionRuling` involved). Starts
  at `1.0` (max) for an unexamined target and shrinks as assertions accumulate — it
  auto-updates by construction, exactly per F16. `stats_for_target` (line 104) already
  defines the precedence: an operator `DimensionRuling`, if present, supersedes this
  entirely — so reading `half_width` for planning never risks colliding with or
  duplicating the operator's own rulings.
- **F18** ⚠ — `data/live/screen.db` + `data/live/research_traces/d542c029b8fd.jsonl`
  (operator's reported opening, read-only inspection this session) — the actual failure is
  worse than "stops a little early on coverage count." All 12 assertions are timestamped
  the original 2026-08-28 intake pass; the 3 resumed turns (2026-09-02, all `search`, zero
  `fetch`) added **zero** new assertions. The first search's own results included
  `levels.fyi/companies/wheel/salaries/software-engineer` — directly relevant to
  `compensation`, a target with real spread (operator `DimensionRuling.mean=0.53`) — and
  the planner chose `stop` anyway, once citing "coverage is complete" and once claiming
  "no specific URLs from the last search result to fetch," which its own trace
  contradicts. This is the coverage-based stop condition actively suppressing a `fetch`
  it had a good target for, not merely stopping one turn too soon.
- **F19** — `src/screen/research/dispatcher.py:126-152` (`_handle_search`) — confirms the
  mechanical half of F18: `search` only ever populates `last_context` for the next
  `decide_plan` call; it never calls `extract_assertions`. Only `_handle_fetch` (line
  157) does. A pass that never issues `fetch` cannot produce assertions regardless of any
  stop-condition wording — the stop condition and the search/fetch split are two
  independent places this can go wrong, and F18 shows the live failure was the planner
  never choosing `fetch` despite good URLs being available.
- **F20** — operator, this session — `DimensionRuling` is not *only* a scoring override;
  it also signals where the operator wants more evidence. Low `settledness` means "I'm
  not sure, dig here" even if an assertion already exists; high `settledness` means "I'm
  satisfied, stop." The composite "keep digging" signal must read both the operator's
  `settledness` (when a ruling exists) and the assertion-derived `half_width` (when it
  doesn't). A dimension with a low-settledness operator pin and thin assertions is the
  most urgent target; a dimension with a high-settledness operator pin is settled regardless
  of assertion count; an unrated dimension with few/no assertions is also urgent.
- **F21** [x] — operator, this session: the coverage-based stop condition (and any prompt-
  based stop condition) should be removed entirely. The only stop condition is turn-budget
  exhaustion. → `research-targeting.md` §Agreed / §Done When
- **F22** — operator, this session — regarding F14, still too early to tune thresholds off
  one run; the composite signal should be built and exercised, then calibrated after a
  few real passes.

