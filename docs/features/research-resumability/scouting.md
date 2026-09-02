---
feature: research-resumability
type: scouting
date: 2026-09-01
commit: 1fba424
---

## What We're Doing

"We're getting to the point where having resumable research would be really helpful. We
recently added a ruling bandit to manage my efforts in assigning rulings to openings. I'd
also like to have a budget for research turns and/or tokens to resume initial research.
Probably involves making research traces part of the db so that they can be easily linked
to. Or maybe we leave them as blobs and they are first class artifacts?"

## Findings

- **F1** — `src/screen/intake/research_trace_io.py:1-8` — the research trace is already an
  append-only JSONL blob (`append_line`/`read_research_trace`, no truncation path), one
  event per line, replayable. This is the substrate any resumability mechanism would build
  on, not something to design fresh.
- **F2** — review-ux/scouting F7 (operator, prior session) — "research state should be
  *computed*, not stored: if we effectively save the transcript, we can resume state at any
  point and also compute turns... help identify additional/novel search targets rather than
  retreading same ground." This is a standing operator position, not new — this session's
  request is that position coming due.
- **F3** — review-ux/scouting F9 — `LoopState`'s `visited_urls`, `prior_queries`,
  `searches_used`, `tokens_used` are already treated as *per-pass working values*, derivable
  fresh from a transcript replay, not independently persisted facts. Consistent with F2.
- **F4** — `src/screen/intake/cli.py:268-271` — today's search/token budget is per-*pass*
  only, sourced from `SCREEN_SEARCH_BUDGET`/`SCREEN_TOKEN_BUDGET` env vars, reset to 0 used
  at the top of every `_run_dispatch` call. Nothing sums usage across passes; nothing
  tracks how many passes an opening has already had.
- **F5** — `src/screen/types.py:29` (`Opening.research_trace_id`) — one research trace per
  Opening today, 1:1. There is exactly one CLI entrypoint that drives a pass
  (`intake <url>`, `src/screen/intake/cli.py:132`) and it always runs the *first* pass
  (fetch → identify → one dispatch loop). No entrypoint exists today to run a *second*
  pass against an already-identified opening.
- **F6** — domain-model.md §Evidence, `ResearchPass` — described (assigned targets,
  search/token budget, full instrumentation, nomination-for-reopening) but **not
  implemented as code**. `PassSummary` (`src/screen/research/state.py:43`) is the only
  code analog, and it is an ephemeral return value — `dispatch()` returns it, the CLI
  echoes it (`intake/cli.py:279`), and it is discarded. No pass history is persisted
  anywhere.
- **F7** — decisions E5 (`demonstrated` D14, contract `adopted` O6) — the ratified
  contract: passes append, budget is spent only on assigned gaps, incidental evidence
  files free against any target including settled ones, a pass may nominate a settled
  target for reopening (routed, not auto-acted). review-ux/scouting F12 confirms: **no
  code implements the nomination-routing half of this contract yet.**
- **F8** ⚠ — attention-allocation-scouting.md F11/F109/F113 — the *research-pass bandit*
  (as distinct from the built rating bandit) is scoped and discussed at length but **not
  implemented**. Its candidate list is described as depending on "has this opening already
  had N passes / hit its search budget" — a dependency the same findings flag as
  unverified because no per-opening pass count or cumulative budget exists yet (this
  session's request would supply exactly that missing input).
- **F9** — review-ux/rating-voi-triage.md (`status: done`) — the *rating* bandit is built:
  arm = opening, per-opening task budget (`scoring.yaml: rating_task_budget`), a focused
  view. This is the sibling the operator is contrasting against — "we recently added a
  ruling bandit" refers to this leaf.
- **F10** — attention-allocation.md §Approach — both bandits are committed to read one
  shared crossing-probability signal and differ only in the action offered against a
  contested opening. The research-pass bandit's action is presumably "run another pass" —
  not designed yet.
- **F11** — open-questions.md #11 — "How many passes does a decision take?" has zero
  observations; "the search cap should not move until there are several runs to compare,"
  settled by "per-company lifetime instrumentation across the steel thread's one-off and
  batch phases." Resumability is the mechanism that would produce this instrumentation —
  today nothing records it.
- **F12** — AGENTS.md "measure before model" + `scoring.yaml` header comment — every dial
  in this codebase to date (`bar`, provenance weights, `rating_task_budget`,
  `attention_allocation`'s top-K) lives in `scoring.yaml` as a named, operator-owned
  placeholder, explicitly not a code literal and not an env var. Today's search/token
  budget (`SCREEN_SEARCH_BUDGET`/`SCREEN_TOKEN_BUDGET`, `intake/cli.py:268,270`) is the one
  exception — env vars, not `scoring.yaml`. Any new turn/token budget the operator wants
  to reason about (and any *lifetime*-across-passes budget) is the same kind of dial this
  codebase already has a home for.
- **F13** — `src/screen/store/migrations/0001..0005` — the domain/judgment split already
  drawn by the schema: structured facts (`Company`, `Opening`, `Assertion`,
  `AssertionRuling`, `DimensionDigest`, `DimensionRuling`) live in SQLite as typed columns;
  the raw process record (tool calls: `tavily_search`, `tavily_extract`, `decide_plan`)
  lives as an append-only JSONL blob on disk, addressed only by
  `Opening.research_trace_id` (a filename stem, not a foreign key into any table). No
  table today references trace *contents* — only the file's existence.
- **F14** — open-questions.md #15 — migration tooling (Alembic etc.) is explicitly deferred
  until "the table count and join complexity grow past what mapper functions stay cheap to
  hand-write," with hand-written SQL judged sufficient at "three tables, read-only
  endpoints." A persisted `ResearchPass`/pass-log table (if pursued) is exactly the kind of
  schema growth that finding is watching for, not yet past the line by itself.
- **F15** — `src/screen/research/dispatcher.py:60-95` — `dispatch()` is already
  file-agnostic and stateless: it takes a `LoopState` (in-memory), returns a
  `PassSummary`; nothing inside it reads or writes the trace file itself —
  `on_event` callbacks (wired by the CLI) are the only I/O side channel. This means
  "resume from a transcript" is a `LoopState`-construction problem at the CLI/replay layer,
  not a dispatcher change.
- **F16** — `src/screen/intake/events.py:9` (`ToolName` Literal) — trace events are already
  typed and closed (`tavily_extract`, `tavily_search`, `decide_plan`) — a replay reader
  reconstructing `visited_urls`/`prior_queries`/`searches_used`/`tokens_used` from a trace
  file has a fixed, small vocabulary to fold over, not an open-ended parse.
- **F17** [x] — closed by operator: not intent on token spend specifically — "it could also
  be number of research actions/turns." The budget unit is turns/actions, not tokens;
  token metering (F17's original question — nothing computes it today) is out of scope →
  §Not Doing.
- **F18** [x] — closed by operator: intake becomes internally driven, one mechanism each
  time — "we have state and then we run the loop until a stop condition is met." No
  fork between "first pass" and "resumed pass": both are the same shape (construct
  `LoopState` from whatever budget/coverage exists so far, run `dispatch` until stop).
  "Replace vs. add a second entrypoint" (my framing) was a false dichotomy — there's one
  loop-running mechanism; intake is just its first invocation → §Approach.
- **F19** [x] — closed by operator: lifetime turns budget is **per opportunity** (per
  opening), not per-pass. But the *research bandit* operates on a global pool: it allocates
  turns across opportunities and then runs reconciliation against actual-vs-desired spend.
  This reframes the work from "make a single opening's second intake call resumable" to
  "provide a substrate that lets a research bandit allocate turns across openings, each of
  which resumes from its trace up to its own lifetime cap." (→ operator, this session)
- **F22** [x] — closed by operator: global pool = fixed number of turns per batch
  ("Today, let's do another 30 turns of research across the opportunities that would
  benefit the most"). Reconciliation = compare actual vs desired per opening and run more
  turns to close the gap ("Vetco has budget 12, completed 7, run 5 more"). The
  algorithmic "which would benefit most" selection is deferred to a separate bandit-bearing;
  this bearing needs the bookkeeping substrate that makes both manual triggers and the
  later bandit possible (→ operator, this session; splits F8/F10 bandit work into a
  dependent bearing)
- **F23** [x] — closed by operator: steel-thread per-opening cap is set at intake from a
  single `scoring.yaml` dial, with a manual override/bump mechanism per opening. Existing
  openings are seeded with that dial value. No queue-position heuristic in this bearing; the
  bandit-bearing may later drive the per-opening cap algorithmically → §Approach, §Agreed.
- **F24** [x] — closed by operator: one turn = one `tavily_search` or `tavily_extract` action
  (budget-consuming research action), not a full plan/act cycle. The old `search_budget` and
  `token_budget` collapse into a single `turn_budget` → §Approach, §Agreed.
- **F25** [x] — closed by operator: no separate `default_desired` vs `initial_research_turns`
  dials. Each opening starts with an initial budget from `scoring.yaml` and can be bumped up
  per opening. The single dial is the opening's lifetime cap; intake consumes part of it,
  leaving the rest for later research. Simpler than the two-dial split → §Approach, §Agreed.
- **F21** [!] — operator, same answer as F19 — flagged their own reservation: today's
  early-stop condition "every rubric target has ≥1 assertion" doesn't have a clean analog
  once resumability exists, because a lifetime budget implies passes keep going *past*
  first coverage (deepening/corroborating), not stopping the moment every target is
  merely touched. Coverage-based early stop and budget-exhaustion early stop are both live
  stop conditions today (`dispatcher.py`'s search-budget guard vs. the planner's own
  stop decision) and may start pulling in different directions once budget is
  lifetime-scoped → §Recalibrate When.
- **F20** [x] — closed by operator: "no value in per event... just store the blob and be
  able to retrieve as an item linked to opportunity then update when pass complete." One
  row per trace *file* (a durable pointer + retrieval, not exploded events), consistent
  with F5's existing `research_trace_id` linkage — not a schema explosion → §Approach.

## Not Yet Settled (carried into bearing discussion)

- F21's tension (coverage-based vs. budget-based early stop) is flagged as rideable, not
  blocking — carried as a Recalibrate When condition rather than resolved now.
- Exact mechanism for the manual per-opening bump (a CLI flag, an editable field, a small
  command) — implementation detail, not yet pinned.
