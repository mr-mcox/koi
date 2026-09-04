---
feature: research-pass-bandit
type: scouting
date: 2026-09-04
commit: 3e76d7d
---

## What We're Doing

`docs/CURRENT.md`'s framing: which opening benefits most from the next research-pass
batch turn, and how a per-opening budget heuristic would replace the flat seeded dial —
deferred out of research-targeting, research-fetch-resilience, and research-resumability
(each bearing's §Not Doing names this as a separate, dependent future bearing).

## Findings

- **F1** — `research-resumability/bearing.md` §Not Doing — "Any heuristic that sets a
  per-opening budget from queue position — budget is one flat seeded dial plus manual
  bump; the heuristic belongs to the bandit-bearing." This bearing is exactly that
  successor.
- **F2** — `research-resumability/bearing.md` §Approach — `research_batch` (the CLI's
  `research-batch` command, `src/screen/intake/cli.py:297-335`) is "a simple deterministic
  fill: process openings with remaining budget in a stable order, one turn at a time,
  round-robin, until the batch or all budgets are exhausted. The algorithmic bandit
  replaces this allocator later." `_round_robin_pass`/`research_batch` in
  `src/screen/intake/cli.py:297-335` is the concrete allocator this bearing supersedes or
  wraps.
- **F3** — `research-resumability/research-targeting.md` §Not Doing — "Algorithmic
  cross-opening research-pass bandit — this is the *within-opening* planner; the bandit is
  a separate future node." `select_primary_target`/`rank_targets`
  (`src/screen/research/baml_planner.py:94-125`) already solve *which target within one
  opening*; this bearing's job is *which opening*, one level up, using the same
  half-width/settledness signal shape.
- **F4** — `review-ux/attention-allocation-scouting.md` F11 (operator, closed) — the
  operator explicitly distinguishes **two bandits**: (a) research-pass bandit — which
  opening should the agent spend its next research pass on; (b) rating bandit — which
  opening should the operator spend rating minutes on. The rating bandit is built
  (`rating-voi-triage.md`, `status: done`); the research-pass bandit is the one named but
  never built (F8/F10 in that scouting doc), and is this bearing's exact scope.
- **F5** — `review-ux/attention-allocation-scouting.md` F18/F25/F29/F33 (operator, closed)
  — both bandits are meant to consume the **same boundary-crossing signal**: `standing` =
  `P(overall > bar)` per opening, and `crossing_probability` = `P(this opening's `overall`
  trace exceeds the K-th-ranked opening's trace)`, already implemented in
  `src/screen/score/boundary.py:crossing_probability` and wired into `/queue`
  (`src/screen/api/routes.py:104-140`). "Both bandits consume the same boundary
  computation; only the candidate-generation step differs" (F25).
- **F6** — `review-ux/attention-allocation-scouting.md` F25 (operator, closed) — sequencing
  note, not a leverage-computation difference: "research is currently cheaper per unit and
  will be run first." This matches F34 below — research bandit runs before the rating
  bandit in one review session, not interleaved.
- **F7** — `review-ux/attention-allocation-scouting.md` F34 (operator, closed) — the
  operator's actual workflow, already settled: "1. intake new opportunities; 2. run the
  research bandit with a configured budget; 3. run the rulings bandit (operator acts);
  4. decide whether to return to step 2 or 3, or stop and apply to the top L." This
  bearing is what fills in step 2's "with a configured budget" — currently
  `research-batch N`'s round-robin has no opening-selection logic at all, it just cycles
  every opening with headroom.
- **F8** ⚠ — `review-ux/attention-allocation-scouting.md` F19/F20 (operator, closed) — the
  *rating* bandit's candidate generation deliberately does **not** reuse `resolve_favourably`
  / `unexamined_targets` (F4 of that doc: those only detect fully-blank targets, undercounting
  leverage on thinly-examined ones) and does **not** sum per-target swings (F14, dissolved).
  It reduced to "is this opening in the contested set" via `reach` vs. boundary (F18/F19), a
  cheaper check than any swing aggregate. Whatever candidate-generation this bearing writes
  for the research-pass bandit should not silently reinvent the swing-sum or blank-target
  approach the rating bandit already rejected for the sibling problem — same boundary
  primitive, a different reason to act on it (F25: research narrows the bracket via *new
  evidence*; rating narrows it via *ratification*).
- **F9** — `review-ux/attention-allocation-scouting.md` F22/F23/F32 (operator, closed) —
  the boundary/top-K contested set is meant to exclude `applied`/`closed` openings once
  pipeline-stage exists, but `Opening.stage` is **not implemented today**
  (`grep -n "stage" src/screen/types.py` returns nothing) and the operator explicitly
  deferred this ("assume they are all the same lifecycle stage" for now, F32). This
  bearing inherits the same non-blocking gap: it may run over the full backlog
  unconditionally, same as attention-allocation-computation.md did.
- **F10** — `src/screen/score/scorer.py:41-52` (`TargetStats`) — `half_width` is
  half-width of a target's Uniform distribution; `is_unexamined` is `n == 0 and not
  always_examined`. `rank_targets` in `baml_planner.py:94-114` already uses this exact
  provenance-weighted `n`/`half_width` shape (via `_target_uncertainty`) as the per-target
  urgency signal *within* one opening. There is no analogous per-*opening* function today
  — nothing sums or aggregates `TargetStats` across an opening's targets into one
  "how much research leverage remains here" number apart from `reach` itself (`reach`
  already *is* that aggregate, just computed via a hypothetical-Strong-pass counterfactual
  rather than half-width directly — see F8's caution about reusing it).
- **F11** — `src/screen/score/boundary.py` (`crossing_probability`) — pure function,
  `(ScoreResult, ScoreResult) -> float`, already takes two arbitrary `ScoreResult`s; nothing
  in its signature or the route layer restricts it to `standing` vs `standing`. A candidate
  research-pass ranking could compare each opening's `reach` trace, not just `standing`,
  against the K-th `standing` trace using the same function, if `reach` is decided to be
  the more relevant axis for research (F18 in the other doc already frames `reach ≥
  boundary` as the coarse contested-set filter for research specifically — standing is
  used for rating).
- **F12** — `src/screen/api/routes.py:104-140` (`get_queue`) — the queue already computes,
  per opening, `standing`, `reach`, `ceiling`, `unreachable`, and `crossing_probability`
  (against the K-th `standing`-ranked opening) at request time, no persistence. Any
  research-pass ranking this bearing builds can be layered on top of (or read from) this
  same per-request computation rather than adding a new scoring pass.
- **F13** — `src/screen/intake/cli.py:297-335` (`research_batch`, `_round_robin_pass`) —
  the CLI entrypoint takes only `batch_size: int`; it has no notion of "rank by X first."
  Changing its allocation order to something other than DB insertion order
  (`list_openings`, `store/repo.py:120-122`, "oldest first") is the mechanical surface this
  bearing's Approach will touch.
- **F14** — `src/screen/store/repo.py:120-122` (`list_openings`) — returns every opening
  in the DB, oldest-first, no filter. This is `research_batch`'s current candidate source;
  a ranked candidate list would read from the same query and reorder/filter, not add a new
  table or persisted ranking (E5's append-only-evidence spirit and F16 of the sibling doc:
  no new blended field).
- **F15** [x] — closed by operator, this session: coarse contested-set filter as the
  eligibility gate, but the sampling weight itself is finer than `reach ≥ boundary` —
  weighted random sampling by aggregate half-width, not a boolean contested/not filter
  alone (see F20-F22).
- **F16** [x] — closed by operator, this session: resample every turn (redraw one
  opening, spend one turn, recompute, redraw), not one-opening-to-completion. Explicit
  reasoning: committing the whole batch to one opening's argmax risks wasting budget if
  that opening's leads run out, and the goal includes spreading assertions across more
  openings for the rating bandit to work with, not just narrowing one opening fastest.
- **F17** [x] — closed by operator, this session, via F15/F16/F20: aggregate `half_width`
  weighted by `dimension_weights` is the sampling signal — closer to Thompson-sampling-
  style uncertainty-weighted exploration than either `crossing_probability` argmax or a
  `reach`-distance argmax. This also resolves F8's caution for free: summed half-width
  reads *thin* evidence (a target with one weak assertion), not just *blank* evidence,
  where `reach`/`unexamined_targets` only detect fully blank targets.
- **F20** ⚠ — `src/screen/score/types.py:41-51` (`ScoringConfig`) — `dimension_weights` is
  a `dict[str, int]` keyed by scoring dimension only; constraints
  (`config.constraints: dict[str, ConstraintRange]`) carry no analogous weight field —
  `docs/architecture/decisions.md` S2/D7 models them as discount multipliers, not summed
  weighted terms (see `scorer.py`'s `score()`: dimensions are weighted-summed, constraints
  multiply `overall` directly). F6 (review-ux/attention-allocation-scouting.md) measured
  constraints as the dominant real-world lever (302× standing swing from two constraint
  labels) despite having no formal weight. A dimension-weight-scaled half-width aggregate
  therefore has no ready-made weight to scale a constraint's half-width by — needs a
  Closed by operator, this session: constraints receive the same weight as the maximum
  dimension weight (`max(config.dimension_weights.values())`), acknowledging F6's finding
  that constraints are the dominant real-world lever while keeping the heuristic a
  one-line, non-configured policy that's easy to revisit rather than a new `scoring.yaml`
  dial.
- **F21** — `src/screen/score/scorer.py:56-95` (`_target_stats`, `stats_for_target`) —
  computing `TargetStats.half_width` for every dimension/constraint on one opening's
  current assertions is a handful of `sqrt`/sum operations over already-in-memory
  `Assertion` objects — no Monte Carlo sampling (`rng.uniform`, the `size=200_000` draws)
  is needed to get half-widths; that only happens inside `score()`'s dimension/constraint
  sampling loop. Recomputing this aggregate for every opening on every turn (`research-
  batch`'s per-turn resample, F16) is cheap in the same sense `rank_targets`
  (`baml_planner.py:94-114`) already recomputes per-target uncertainty every dispatcher
  turn today — no new performance concern.
- **F22** — `src/screen/intake/cli.py:297-335` (`_round_robin_pass`, `research_batch`) —
  today's loop calls `_resume_opening(conn, data_root, opening, 1)` once per opening per
  round, in DB order. A weighted-resample-every-turn version needs, per turn: (a) load
  every opening with remaining budget, (b) compute each one's aggregate half-width
  from `assertions_for_opening` + `dimension_rulings_for_opening` (mirroring
  `screen.api.routes.get_queue`'s per-opening data assembly, `src/screen/api/routes.py:
  104-125`), (c) draw one opening weighted by that aggregate, (d) spend exactly 1 turn via
  `_resume_opening`, (e) repeat. This replaces the round-robin loop structure, not just its
  ordering — the current code has no per-turn recomputation step at all.
- **F23** — `src/screen/intake/events.py` (`ResearchTraceEvent`, `ToolName` Literal) — the
  per-opening trace already has a precedent for appending a new instrumentation event kind
  in place rather than a new log/table (`research-fetch-resilience/bearing.md` Approach:
  "enrich `ResearchTraceEvent` in place rather than adding a new log or table"). But every
  existing trace event is scoped to *one opening's* trace file
  (`_research_trace_path_for`, keyed by `opening.research_trace_id`); a cross-opening
  sampling decision (which opening was drawn, at what weight, out of what candidate set)
  has no single opening's trace to naturally live in. The operator's ask ("trace what was
  sampled and how order changed") is a `research-batch`-level artifact, not a per-opening
  one — no existing mechanism fits it directly.
- **F24** — `src/screen/intake/cli.py:337-352` (`research_status`) — the existing
  `research-status` command's shape (loop over `list_openings`, `click.echo` one line per
  opening, no persistence) is the cheapest precedent for surfacing the sampling trace: a
  `research-batch` run could `click.echo` one line per turn (opening drawn, its weight/
  probability at that turn, rank position before vs. after) to the same stdout the command
  already writes to, needing no new file, table, or event schema (open-questions.md #15's
  reasoning against premature persistence machinery applies here too — nothing yet
  consumes a stored history of past batch runs).
- **F25** [x] — closed by operator, this session: stdout-only, matching
  `research-status`'s existing posture (F24) — no new file/table/schema. The operator may
  turn the logging off later once satisfied; no persistence machinery is built in advance.
- **F26** [x] — closed by operator, this session: the F24-proposed line shape (opening
  drawn, its sampling weight/probability at draw time, rank-by-aggregate-half-width before
  the turn vs. after the turn's new assertions land) is accepted as-is.
- **F18** [ ] — does an opening that already has `stage` beyond `screening` (once F9's gap
  is eventually filled) get excluded, or is that explicitly out of scope here too, same as
  the rating-bandit sibling deferred it (F32)? Likely inherits the same deferral, but
- **F27** — operator, this session — wants a UI affordance to kick off a research batch
  and set its turn budget from the web UI, not just the CLI. Explicitly fine deferring this
  to a future bearing if this one is already heavy. `src/screen/web/routes.py` has no
  research-triggering route today (`grep -n "research" src/screen/web/routes.py` returns
  nothing) — this would be new surface, not a wire-up of something half-built.
- **F28** — operator, this session — once a UI affordance exists, several CLI commands
  become removable: `bump-research-turns-budget` (`src/screen/intake/cli.py:222-234`, manual
  per-opening override) and `research-batch` itself (`src/screen/intake/cli.py:315-335`,
  the round-robin entrypoint this bearing's Approach already replaces the internals of) are
  named as "temporary CLI" the operator expects to retire once the UI affordance lands.
  `backfill-research-turns-budget` (`cli.py:176-189`) is not named — it's a one-time
  migration helper, not a manual-override surface, and isn't implicated by the same
  reasoning.
  should be confirmed as an explicit Not Doing rather than silently assumed.
- **F19** — `docs/features/research-resumability/bearing.md` §Recalibrate When — "The
  simple round-robin batch allocator leaves the operator manually micro-managing which
  opening gets the next turn — a signal that the bandit-bearing should be picked up." This
  is the trigger condition that, per that bearing, licenses starting this one now.
