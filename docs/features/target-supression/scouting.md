---
feature: pairwise-ranking
type: scouting
date: 2026-09-21
commit: (pending)
branch: rank-pool
---

## Trigger

A live batch run after `research-targeting.md` shipped showed roughly half its draws
adding zero new assertions. Two traces (were pulled
directly and both show the same pattern: the planner stays sticky on one target
(`agentic`, `non_scoring:obtainability`) across a whole 3-action block, issues
near-identical search queries, gets no fetchable hit, and burns the block — then a
*later, separate* `resume_opening` call re-ranks from scratch, sees the same target's
assertion count unchanged (still the highest uncertainty), and repeats the exact same
dead end. Filed by the operator as: "on the planner level, if after two searches on a
target nothing gets added, disallow/suppress that target — can we use the trace history
to suppress it in weight?"

## F1 — the per-pass guard already exists and already fires; the bug is across passes

`active_target_action_cap` (`research_target_action_cap: 3` in `scoring.yaml`) already
stops a sticky session at 3 actions on one target within a single `run_dispatch` call —
`select_primary_target` (`baml_planner.py:96-110`) releases the target once
`active_target_actions >= active_target_action_cap`. Both live traces show this firing:
Vetcove's `agentic` session ran exactly 3 turns (7→9 used) before turn_budget also hit,
Airbnb's `obtainability` session ran 3-4 actions before release. The guard is not broken.
[confidence: high — read directly from the two live trace files, `dispatcher.py:70-87`,
`baml_planner.py:96-110`]

## F2 — `active_target`/`active_target_actions` are `LoopState` fields, reset every call

`run_dispatch` (`batch.py:147-`) builds a fresh `LoopState` per call with
`active_target=None`, `active_target_actions=0` unconditionally (`batch.py` state
construction; `LoopState` defaults in `state.py:46-47`). Neither field is threaded
through `TraceReplay` the way `turns_used`/`visited_urls`/`prior_queries` are. So a
`resume_opening` call that starts a fresh pass has no memory of "target X was just
maxed out and failed" — it only has `state.assertions` (unchanged, since the failed
session added none) and `prior_queries` (raw query strings, not structured
per-target outcome). [confidence: high — read `state.py`, `research_trace_replay.py`,
the `run_dispatch` call site in `batch.py`]

## F3 — `rank_targets` is blind to attempt history entirely

`rank_targets` (`baml_planner.py:80-89`) computes `1/sqrt(n+1)` per target from
`_assertion_weight_by_target`, purely off the current assertion list. A target that was
searched three times and found nothing has the exact same score as a target that has
never been touched — both have `n=0`. This is why the same dead-end target wins the
re-rank every time: nothing in the signal distinguishes "unexamined, promising" from
"examined via search, unproductive." [confidence: high — read the function directly]

## F4 — the planner does see raw query text, and mostly avoids literal repeats

`TraceReplay.prior_queries` (`research_trace_replay.py:32-36`) folds every
`tavily_search` query ever issued for the opening, across all resumes — not scoped to
one pass. `_prior_queries_text` (`baml_planner.py:22-30`) renders the full list into the
prompt with the instruch "Avoid repeating a query already in prior queries." The live
Vetcove queries were in fact reworded each time (not literal repeats), so the model is
following that instruction — the failure is that rewording a query for an unanswerable
target doesn't help; the target itself needed to be dropped, not the phrasing. Nothing
in the current prompt or ranking signal tells the model "this whole target is likely a
dead end," only "here's what you already tried." [confidence: high — read the two live
traces' actual query strings, `baml_planner.py`'s prompt template in `research.baml`]

## F5 — a target's outcome (assertions added) is reconstructable from the trace alone

Every `decide_plan` event's `request` snapshot (`_plan_request`, `dispatcher.py:45-67`)
records `active_target` and `active_target_actions` for that turn. The dispatcher writes
one `decide_plan` event per turn (`dispatcher.py:111-120`), and the *next* turn's
`last_context` (rendered from `FetchContext.targets_added` or `SearchContext.hits`) shows
what that turn produced. So walking the trace linearly and tracking, for each contiguous
run of turns sharing the same `active_target`, whether any `tavily_extract` event's
resulting assertions included that target, reconstructs a per-target history of
"attempted, productive" vs "attempted, stalled" without any new persisted field — matches
the existing invariant that `TraceReplay` derives everything from the trace file, never a
second copy that could drift (`research_trace_replay.py` module docstring).
[confidence: medium — the mechanism is sound and traceable by inspection, but no code
path today extracts targets-per-turn from a fetch's assertions; this would need to
either (a) read `FetchContext.targets_added` off the `last_context` recorded in the
*next* `decide_plan` event's `request` snapshot, or (b) independently know which new
assertions (by created_at ordering, or by diffing consecutive `decide_plan` calls'
`targets_covered`) arrived during that specific active-target run. (b) is simpler:
`_targets_covered` (`dispatcher.py:40-42`) is already recorded in every
`decide_plan.request.targets_covered` list — a target's appearance there for the first
time, occurring within a given active-target run's turn range, marks that run
productive.]

## F6 — turn-level attribution is coarser than assertion-level: a stalled search still counts as "attempted"

A `tavily_search` event that returns hits but no fetch follows is, from the trace's
perspective, just a turn with `active_target=X`. Whether *that specific turn* helped
target X can only be inferred by whether `targets_covered` grew to include X sometime
during or after the run's turn range — not turn-by-turn, since a search's hits are
consumed by the *next* turn's fetch decision, and a fetch's targets_added can span
multiple targets (a hub page). This matters for the operator's stated trigger ("after
two searches on a target, nothing gets added") — "two searches" is a per-run action
count (already tracked via `active_target_actions`), and "nothing gets added" is
best measured as "target X was not in `targets_covered` before the run and still isn't
after it ends" — i.e. per active-target-run, not per individual search action.
[confidence: medium — reasoned from the data shapes in F5, not yet implemented or tested]

## F7 — cooldown needs a magnitude, not just a boolean flag; operator wants an S-curve

The operator explicitly asked for graduated suppression: "after one, suppresses
slightly, at two it gets knocked lower, at 3+ it's unlikely ever to be tried again" — not
a hard cutoff. This matches the existing pattern of `boundary_weight` in
`score/bandit.py` (a pure `p -> float` shaping function, no state) and the general
project stance against hard gates (S-decisions reject gates-as-weights per
`AGENTS.md`/`decisions.md`). A multiplicative penalty applied to a target's
`rank_targets` score, keyed by "number of unproductive active-target runs for this
target, this opening, ever" is the natural fit — mirrors `boundary_weight`'s role as a
second pure shaping function layered onto uncertainty in `research-targeting.md`'s
already-agreed pattern (product of two independent pure functions, not a rewrite of the
base signal). [confidence: high — direct read of the operator's request plus the
existing `research-targeting.md` §Approach precedent]

## F8 — worked numeric shapes for the S-curve, three candidate families

Let `s` = number of unproductive stalls for a target (0 = never stalled or always
productive). Want: `suppression(0) = 1` (no penalty), a gentle dip at `s=1`, a sharper
one at `s=2`, and `suppression(s>=3) ≈ 0` (~never picked again absent new assertions
elsewhere shifting the ranking, though never literally zero — a hard zero would make a
target permanently unselectable even if it becomes the only unexamined one left, which
contradicts "no organic refill... but not an outright ban" instinct raised for the
budget removal; a small floor keeps every target theoretically reachable if nothing else
is left).

Family A — logistic decay, `suppression(s) = 1 / (1 + exp(k*(s - m)))` centered at
`m=1.5`, steepness `k=4`:

| s | suppression |
|---|---|
| 0 | 0.994 |
| 1 | 0.881 |
| 2 | 0.119 |
| 3 | 0.006 |
| 4 | 0.0003 |

Family B — squared-reciprocal, `suppression(s) = 1 / (1 + s^2)`:

| s | suppression |
|---|---|
| 0 | 1.000 |
| 1 | 0.500 |
| 2 | 0.200 |
| 3 | 0.100 |
| 4 | 0.059 |

Family C — geometric, `suppression(s) = r^s` for `r=0.15`:

| s | suppression |
|---|---|
| 0 | 1.000 |
| 1 | 0.150 |
| 2 | 0.0225 |
| 3 | 0.0034 |
| 4 | 0.0005 |

Family A (logistic) is the only one that gives a genuinely *slight* dip at `s=1`
(0.881, an ~12% cut) while still reaching a near-floor by `s=3` (0.006) — matching the
operator's three-tier description almost verbatim ("slightly" / "knocked lower" /
"unlikely ever"). Family B's `s=1` cut (50%) is too aggressive for "slightly." Family
C's `s=1` cut (85%) is far too aggressive — it's already at "unlikely ever" after one
stall, which contradicts the graduated ask. [confidence: high — arithmetic checked
directly; family choice is a judgment call for the operator to confirm, not a settled
finding]

## F9 — where the penalty applies: multiply the per-target uncertainty score, not the pool-level draw weight

`rank_targets` returns `[(target, uncertainty)]` sorted descending; `select_primary_target`
picks `ranked[0][0]`. The natural insertion point is
`uncertainty * suppression(stall_count)` per target before sorting — same shape as
`research-targeting.md`'s `uncertainty * boundary_weight(p_top_k)` at the opening level,
one level down. This keeps the two mechanisms structurally parallel and independent:
opening-level draw weight (which opening gets a turn) is untouched; target-level
ranking (which target that turn spends on) gets the new term. No cross-talk needed.
[confidence: high — read `rank_targets`/`select_primary_target` directly, confirms the
insertion point is a pure addition to an existing pure function's inputs]

## F10 — `LoopState` needs a new field to carry stall counts in; sourced from `TraceReplay`, not persisted separately

Following the pattern of `visited_urls`/`prior_queries` (computed by
`replay_research_trace`, passed into `LoopState` at `run_dispatch` construction time,
never written to a DB column), stall counts per target should be a new
`TraceReplay` field (e.g. `target_stalls: dict[str, int]`) computed by walking the trace,
and a new `LoopState` field (e.g. `target_stall_counts: dict[str, int] = {}`) populated
from it in `batch.py`'s state construction. This avoids a schema change entirely —
matches the just-completed precedent of deriving everything from the trace file
(`research_trace_replay.py` docstring) and the recent decision to remove a persisted
counter (`research_turns_budget`) rather than add one. [confidence: high — direct
parallel to existing code structure, no new risk identified]

## F11 — reconstructing stall counts requires walking active-target runs, more involved than the existing fold functions

`replay_research_trace`'s existing fold functions (`_fold_search_event`,
`_fold_extract_event`) are per-event, streaming, and don't need to look back. Counting
"unproductive active-target runs per target" requires segmenting the event stream into
contiguous same-`active_target` runs (from each `decide_plan` event's
`request.active_target`) and, for each run, checking whether `targets_covered` grew to
include that target's slug by the run's end (comparing the `decide_plan` event that
opens the run to the one that opens the next run, or to the final state).
This is a genuinely new fold, not a trivial extension of the existing two — likely wants
its own helper function and its own focused unit tests (a runnable synthetic trace
fixture, not a mock of the whole dispatcher). [confidence: medium — architecture is
clear from F5/F6, but no code written or tested yet; this is the single largest
implementation surface in this feature]

## F12 — does a stall count ever decay or reset? No found reason to reset it

Nothing in the domain model suggests a target's failure history should be forgotten —
a target search is either found or effectively concluded not-searchable via the modes
available (search + fetch), and the assertion count for it can still change via other
paths (a fetch on a *different* active target incidentally adding evidence for it, per
`targets_covered`'s cross-target crediting already visible in the Samsara trace excerpt
in the live run: "added assertions for the primary target (agentic) plus peer,
internal_culture, schematic, and trajectory"). If a target picks up an assertion via
this side-channel, `rank_targets`'s base uncertainty term already drops for it
naturally (`n` increases), independent of the suppression multiplier — so no explicit
reset of the stall counter is needed; the base score falling does the equivalent work,
and the multiplier just continues decaying the previously-stalled target's rank further
if directly re-attempted and still fruitless. [confidence: medium — reasoning from the
existing signal composition, not empirically verified against a case where this matters
in practice]

## F13 — this is a new bearing, not an expansion of research-targeting.md

`research-targeting.md` is already shipped (status: implementing → its Done When items
1-4 are checked, 5th confirmed live) and operates one level up: which *opening* draws a
turn (`eligible_weights` in `batch.py`, `score/bandit.py`). This new mechanism operates
one level down: which *target* a turn is spent on once an opening is drawn
(`rank_targets`/`select_primary_target` in `baml_planner.py`,
`research_trace_replay.py`). Different files, different signal, cleanly separable —
matches `research-targeting.md`'s own "Not Doing" note (F10 there: "Changing
`baml_planner.rank_targets`... orthogonal, operates one level down"), which already
flagged this as future, separate work. [confidence: high — direct cross-reference to the
already-written and operator-approved bearing]

## F14 — testing surface mirrors `test_bandit.py`'s boundary_weight tests

`boundary_weight` (`score/bandit.py`) has two direct unit tests in `tests/test_bandit.py`
checking shape (maximized at 0.5, zero at extremes, symmetric). A new
`target_suppression(stall_count: int) -> float` pure function in the same module (or a
sibling) can get the same treatment: monotonically non-increasing, `suppression(0) == 1`
(or ~1), roughly matches the chosen family's table from F8. Then `rank_targets`'s
existing tests (`test_rank_targets_prefers_unexamined_target`,
`test_rank_targets_falls_back_to_assertions` in `test_baml_planner.py`) get a new
sibling asserting a stalled target ranks below an unexamined one even with equal
assertion counts. The trace-walking fold function (F11) needs its own fixture-based
tests analogous to `tests/test_research_trace_replay.py`. [confidence: high — direct
mapping to existing, established test patterns]
