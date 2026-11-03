---
feature: research-target-opportunity
type: scouting
date: 2026-11-03
---

## What we're changing

The research planner should be able to choose among several plausible targets instead of being handed one opaque `primary_target`. The operator wants the model to exploit uncertainty plus opportunity: unexplored target space, novelty of question, likely yield, and extension from what is already known. A related seam: when a page has promising outbound links, the pass should keep a backlog of URLs it can return to later instead of treating the last page as the only place to look.

## Findings

- **F1** — `src/screen/baml_src/research.baml:31-100` — `DecidePlan` already receives `rubric_text`, `primary_target`, `last_context_text`, and `prior_queries`. So the planner already knows what it is falsifying/validating against, plus a little history of what it has tried.
- **F2** — `src/screen/research/state.py:18-56` and `src/screen/research/batch.py:110-126` — pass state already carries the right raw ingredients for a longer leash: `visited_urls`, `prior_queries`, `active_target`, `active_target_actions`, `active_target_action_cap`, and `target_stall_counts`. The batch engine sets the cap from `scoring_config.research_block_turns`, so a target can keep the pass for several actions before re-ranking.
- **F3** — `src/screen/research/baml_planner.py:81-113` — target choice is currently deterministic. The planner ranks targets from assertion-derived uncertainty plus stall suppression, then chooses the top one (or keeps the sticky target until the cap is hit). There is no candidate shortlist or explicit model choice among multiple targets yet.
- **F4** — `src/screen/research/dispatcher.py:51-89` and `src/screen/research_trace/events.py:31-59` — `DecidePlanRequest` records `targets_covered` and `target_assertion_counts`, which means traces can already tell us what had been discovered at each decision point and whether a target grew during a run. That is enough to measure yield-by-target from existing traces without inventing new history fields.
- **F5** — `src/screen/research/context.py:15-40` and `src/screen/research/baml_planner.py:34-57` — the last action context is already visible to the model, including search hits (with titles/URLs/snippets) and fetch snippets plus `targets_added`. This gives the planner some link-following visibility today, but it is still stringified context, not a structured backlog of candidate outbound URLs.
- **F6** — `src/screen/research/dispatcher.py:191-259` — the only supported actions are `search`, `fetch`, and `stop`. “Navigate to a link from a prior page” is already just `fetch`, but the planner only gets that option if the link appears in the last context text or it re-finds it via search; there is no separate navigation action and no persistent candidate-URL queue.
- **F7** — `src/screen/research_trace/replay.py:116-149` — the trace replay already reconstructs per-target stalls from `decide_plan` events. That makes it possible to derive target-specific yield/stall history from existing traces, which is the missing ingredient if we want the planner to prefer dimensions that actually produce assertions.
- **F8** — `src/screen/research/baml_src/research.baml:107-256` — the current prompt already has a long leash for page mining within a target: a fetch can keep revealing relevant links, and the planner is told not to stop just because the last action did not immediately produce a new assertion. So the missing piece is not the leash itself; it is better surfacing of promising follow-on URLs and better target-opportunity ranking.

## Notes / implications

- A richer target object full of prose is probably not the right first move; the current system already has enough text surfaces.
- The more useful shape is likely: a small ranked set of candidate targets plus compact per-target stats, and a separate structured backlog of outbound links harvested from pages.
- Existing traces should remain readable by keeping any new fields optional and deriving the new rankings from trace-replay-compatible history rather than rewriting the trace format.
