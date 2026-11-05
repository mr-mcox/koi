---
feature: outbound-link-backlog
type: bearing
date: 2026-11-05
commit: 8ab69d1
branch: main
status: implementing
scouting: ./scouting.md
---

## Problem

Links past character 500 drop out of the planner's context immediately, and even visible links vanish after one turn. We want to persist promising outbound links across a research pass so the navigator doesn't have to strike gold instantly, allowing a page with several useful links to keep yielding follow-up fetches without a new search. Terrain: [scouting.md](./scouting.md)

## Done When

- [x] Replaying a trace populates `unvisited_links` in `TraceReplay`, and `dispatch` scores them into a `link_backlog` (up to ~20 items) → test against a mock trace `tests/research_trace/test_replay.py`
- [x] Extracting links ignores hosts that refuse automation → test using `intake/admission.py` mock
- [x] Links are scored using a Jev model (rubric + link text) and ranked, keeping only the top ~20 → verifiable via `tests/verdict/test_jev_link_scorer.py`
- [x] The link backlog is appended to the `Navigate` prompt context → snapshot test on prompt input
- [x] An uncommitted script runs the backlog pipeline over a trace and outputs the rank of any actually-followed links. → verified against the live traces from F12 during agent session: 9/10 in top 20 after the Jev scorer plus aggregator-host filter (→ scouting F16)

## Approach

- Parse markdown links `[text](url)` from the `raw_content` of stored `ExtractResult` events on replay. (→ scouting F3, F5)
- Filter out links pointing to hosts in the `intake/admission.py` blocked list, extended with a short list of large aggregator/job-board hosts (`linkedin.com`, `hiringcafe.com`, `levels.fyi`, `remoterocketship.com`, `img.logo.dev`) before the 100-candidate cap — these hosts' nav/sidebar chrome is what was flooding candidate pools, not a company's own content. (→ scouting F7, F14, F15)
- Score the remaining unvisited links using `jev` against the active rubric dimension to rank them, and keep the top ~20. (→ scouting F8, F9)
- Append the ranked backlog to the state passed to `Navigate`, making it visible to the planner for subsequent turns. (→ scouting F1, F2, F10)

## Not Doing

- Changing how fetches work (e.g. asking Tavily for different formats) — anchor text is already recoverable from the markdown. (→ scouting F4, F5)
- Changing the model's action schema — the planner still just emits `fetch(url)`.

## Testing

Test-first by default. Exempt:
- `src/screen/baml_client/` — generated

## Recalibrate When

- If outbound-link backlog visibility does not improve follow-through on fetched pages.
- If `jev` classification takes too long per batch block or costs too much.
- **Resolved**: the 100-candidate pre-score cap dropped the chosen link on 6/10 of F12's full population (→ scouting F14); the aggregator-host filter above raised this to 9/10 with no batching or cap increase (→ scouting F15, F16). The one residual miss is a company's own careers-subdomain nav chrome, not an aggregator - a distinct, smaller text-pattern filter could close it later but doesn't block this feature. If a future live check finds a non-aggregator host regularly dominating a candidate pool and pushing a real link out of the top 100, stop and revisit.

## Agreed

- Filter out hosts that refuse automation before adding links to the backlog, not just passing them to the model — these are known dead weights. (→ scouting F7)
- Use Jev (TypeSafe's System One) to score the likelihood of relevance based on link text and the rubric, rather than filtering deterministically or delegating to the planner — calibrated probabilities, cheaper than a text generator, and easy to batch across links. (→ scouting F8)
- Cap the backlog at ~20 links, ordered by score, rather than keeping all links - bounds prompt size. (→ scouting F9)
- Agent can perform read-only validation against `data/live` to test backlog ranking via an uncommitted script. (Exception to AGENTS.md §Privacy for this validation)
