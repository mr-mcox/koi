---
feature: research-fetch-resilience
type: bearing
date: 2026-09-03
commit: 3df2f87
status: done
scouting: ./scouting.md
---

## Problem

Tavily transport failures (404s, extraction refusals, possible bot-blocking) abort the research pass and the intake command today. We need to degrade gracefully when an alternate research path exists, and record durable failure artifacts in the trace so the operator can inspect and decide how to address them. Terrain: [scouting.md](./scouting.md).

## Done When

- [x] `TavilyBrowser` surfaces failure details (Tavily response status, `failed_results`, exception text) on `BrowserError` so callers can log them, but does not attempt fine-grained classification because Tavily collapses 403/404/JS-app failures into the same generic message — test: `tests/test_browser.py`
- [x] `_handle_fetch()` catches `BrowserError`, records a `tavily_extract` event with the raw failure details, adds the URL to `visited_urls`, and returns state so the planner can continue with a different lead — test: `tests/test_dispatcher.py`
- [x] `_handle_search()` catches `BrowserError`, records a `tavily_search` event with the raw failure details, and returns state with an empty `SearchContext` so the planner can refine the query — test: `tests/test_dispatcher.py`
- [x] Failed research actions still count as consumed turns (the API call was made), and `research-status` shows them so the operator can see wasted budget — test: `tests/cli/test_pipeline.py` + `tests/test_research_trace_replay.py`
- [x] The initial intake URL failure remains fatal (no content to identify), but `_fetch_url()` records the raw failure in the trace and exits with a clear `ClickException` instead of an unhandled traceback — test: `tests/cli/test_pipeline.py`

## Approach

- Add a `BrowserError.details` dict populated from the Tavily response/exception, but keep `BrowserError` as a single exception type. No change to `BrowserProtocol` call signatures; callers still catch `BrowserError` (→ scouting F1, F2, F15, open space).
- Catch `BrowserError` in `_handle_search` and `_handle_fetch`, record the failure as a trace event with the raw Tavily response in `response` (or a new `tool_error` field if the response shape needs it), and return updated state that lets the planner continue. Keep the dispatcher as the owner of every tool call and its effects (→ scouting F3, F4, decisions E5).
- No automatic retry, no headless-browser fallback, and no bypass for bot-blocking. Respect the Zocdoc/DataDome block and the Workday JS-app limitation by recording them and moving on; the operator decides whether to use a future manual posting fallback (→ scouting F11, F13, F14, operator).
- Keep the trace as the single durable artifact for failures; enrich `ResearchTraceEvent` in place rather than adding a new log or table (→ scouting F6, F7, decisions E5).
- Treat the initial intake URL as a special case: no content means no `Opening`, so the CLI still aborts, but only after the raw failure is written to the trace (→ scouting F5, F14, operator).
- Keep failed actions as budget-consuming turns so the operator can see wasted API spend in `research-status` and bump budgets accordingly (open space).

## Not Doing

- Automatic retry/backoff for transient failures — record and let the operator decide (→ operator).
- Bypassing bot-blocking with a headless browser (`playwright`) or HTTP probe — we honor blocks and JS-app limitations, not work around them (→ operator, scouting F11, F13, F14).
- Fine-grained failure classification (404 vs 403 vs JS-app) from Tavily's generic error string — we record raw details instead (→ scouting F15).
- The algorithmic research-pass bandit — still a separate, dependent bearing (→ parent research-resumability/bearing.md §Not Doing).
- A separate failure log outside the trace; the trace is the durable artifact (→ scouting F6, F7).
- Token-based accounting or per-event DB rows (→ research-resumability/scouting F17, F20).

## Testing

Test-first by default. Exempt: nothing named.

## Recalibrate When

- Classification keeps miscategorizing bot-blocks as 404s or vice versa, so the operator can't trust the artifact. (Not expected to happen since we are not classifying; fires if we later try to.)
- Failed actions counting as turns cause the planner to spin through dead URLs and exhaust budget without useful work.
- The initial intake URL failure turns out to need a graceful fallback (e.g., a manually supplied posting text) rather than a fatal abort — this is the planned future feature, not this one (→ scouting F14, operator).
- We discover we need to actually fetch blocked pages through a secondary mechanism, not just record the failure.

## Agreed

- No retry / no bypass for bot-blocking; record and move on, operator decides (→ operator, scouting F11, F13).
- Failed research actions keep the pass alive and record raw details in the trace, not crash it (→ operator, scouting F9).
- The trace is the single durable failure artifact; no new log or table (→ scouting F6, F7, operator).
- Failed actions count as consumed turns so the operator can see API waste in `research-status` (open space).
- Fine-grained classification is out; record raw Tavily failure details because the API message is generic (→ scouting F15, operator).
