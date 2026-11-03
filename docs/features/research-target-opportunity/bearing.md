---
feature: research-target-opportunity
type: bearing
date: 2026-11-03
status: orienting
scouting: ./scouting.md
---

## Problem

The research planner is already getting the rubric, prior queries, and last action context, but it still has too little structured opportunity signal to choose well among dimensions or keep mining a good page without churning. We want the planner to stay focused enough to continue in the same direction when a page or target still has promise, while also making promising outbound links from fetched pages available later as a backlog instead of forcing the pass to strike gold immediately.

Terrain: [scouting.md](./scouting.md)

## Done When

- [ ] `DecidePlanRequest` carries a compact, trace-compatible shortlist of candidate targets with only deterministic data the dispatcher can compute from existing traces and the live pool → covered by planner/request shape tests
- [ ] `DecidePlanRequest` or its supporting context carries a structured backlog of promising outbound links harvested from prior fetches, including the URL and the visible text/snippet that made each link worth keeping → covered by research-context tests
- [ ] The planner can continue along the same target for multiple actions under the existing sticky-target leash, and a page with several useful links can keep yielding follow-up fetches without requiring a new search every turn → covered by batch/dispatcher tests and a trace replay fixture
- [ ] Existing traces still load and replay without migration, with any new planner fields remaining optional and the replay path falling back to the old behavior when they are absent → covered by research-trace replay tests
- [ ] `uv run python scripts/check.py` passes

## Approach

- Keep planner context focused: the model should see a small ranked shortlist of candidate targets, not a free-form essay per target.
- Make the shortlist deterministic and compact: use current assertions, recent target stalls, and expected ranking impact to propose candidate targets; do not add another model-generated pre-summary layer.
- Expose page opportunity as structured context, not implicit text hunting: when a fetch reveals promising outbound links, retain them as a backlog the planner can revisit later by URL.
- Preserve the existing action vocabulary (`search`, `fetch`, `stop`); visiting a discovered link is still a fetch, but the link must remain visible after the page that exposed it is no longer the immediate context.
- Keep the current moderate leash: `research_block_turns` / `active_target_action_cap` continue to let a target keep the pass for several turns, so a useful page can be mined before re-ranking.
- Prefer optional fields over schema churn: add planner/context fields in a way older traces can ignore, and derive new rankings from replayable trace data rather than rewriting the trace format.

## Not Doing

- Free-form prose per target or a strong-model-generated target essay — the planner needs structured opportunity, not another layer of narration.
- `last_success_turn` or similar bookkeeping that only says when a target last worked — yield history matters more than a timestamp.
- A new navigation action separate from `fetch` — discovered URLs are still fetched, not a new verb.
- Forcing the planner to switch targets every turn — that would create churn and defeat the sticky-target leash.
- Requiring a trace migration before the new planner/context fields land — existing traces must keep replaying.

## Recalibrate When

- If the shortlist becomes so large or wordy that the planner starts churning between targets instead of mining one useful line of inquiry.
- If outbound-link backlog visibility does not improve follow-through on pages with multiple relevant links.
- If a structured link backlog proves too brittle to carry through trace replay without widening the prompt again.
- If the planner still cannot keep going in the same direction after a useful fetch, even with the existing sticky-target cap.
- If additive backward compatibility (decisions.md E8) forces a pile of optional/null fields or
  branching read paths to keep old traces replaying, stop: a versioned trace schema plus a
  compatibility layer that upconverts old lines is likely cheaper than growing one payload
  forever. That supersedes E8's "payloads only grow" rule, so it is an escalation and needs a
  decisions.md entry, not an in-feature call.

## Agreed

- The rubric stays visible to the planner so it knows what each dimension is trying to falsify or validate.
- The planner gets a small deterministic shortlist of candidate targets rather than a larger free-form target essay.
- Promising outbound links from fetched pages should be retained as structured backlog so future turns can revisit them directly.
- The existing action vocabulary remains unchanged: `search`, `fetch`, `stop`.
- Existing traces must keep loading and replaying; new fields, if any, are optional and backward compatible.
