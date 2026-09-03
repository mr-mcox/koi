---
feature: research-fetch-resilience
type: scouting
date: 2026-09-03
commit: 3df2f87
---

## What We're Doing

Handle Tavily transport failures during research so the pass doesn't abort when an alternate path exists (e.g., a 404 on a search-result URL). Record enough detail in the durable trace that the operator can inspect what failed and decide how to address it, including the case where Tavily reports it cannot extract a page that the operator can view in a browser (possible bot-blocking).

## Findings

- **F1** — `src/screen/browser.py:53-57` — `TavilyBrowser.extract()` wraps any Tavily exception in a generic `BrowserError(str(exc))`, swallowing HTTP status codes, structured error payloads, and whether the failure is transient (rate limit) vs. permanent (404/bot block).
- **F2** — `src/screen/browser.py:59-68` — `TavilyBrowser.fetch()` raises `BrowserError` if a URL lands in `failed_results` or returns no results; there is no classification or alternate-path handling.
- **F3** — `src/screen/research/dispatcher.py:181-198` — `_handle_search()` calls `deps.browser.search()` without catching `BrowserError`, so a single failed search aborts the entire research pass.
- **F4** — `src/screen/research/dispatcher.py:226` — `_handle_fetch()` calls `deps.browser.fetch()` without catching `BrowserError`, so a single failed fetch aborts the entire research pass.
- **F5** — `src/screen/intake/cli.py:332-342` — `_fetch_url()` catches `BrowserError` only to record a `tavily_extract` event and then re-raise as a `ClickException`; the initial URL failure is still fatal, but the trace is preserved.
- **F6** — `src/screen/intake/events.py:25-39` — `ResearchTraceEvent` has an open `response: dict[str, Any]` and a comment explicitly inviting fields like `tool_error`, so failure details can be added without splitting the root model or changing the trace schema.
- **F7** — `src/screen/intake/research_trace_io.py:1-8` / `src/screen/intake/research_trace_replay.py:53-71` — the trace is already the durable, append-only source of truth; replay computes `turns_used`, `visited_urls`, and `prior_queries` from it, so failure events can be folded into the same substrate.
- **F8** — operator — frequent Tavily failures in research include 404s and pages that Tavily cannot extract but that render fine in a browser, raising the possibility of bot-blocking that should be respected/detected rather than silently bypassed.
- **F9** — operator — the goal is to not blow up when an alternate path exists (e.g., 404 on a search hit) and to record a durable artifact when a failure does occur so the operator can investigate and decide how to address it.
- **F10** — live Tavily probe — `https://servicetitan.wd1.myworkdayjobs.com/...` returns HTTP 200 from curl but Tavily `extract` returns `failed_results: [{"error": "Failed to fetch url"}]` with both `basic` and `advanced` depth; the page is a Workday JS app with session cookies, so Tavily's fetcher cannot render/parse it.
- **F11** — live Tavily probe — `https://www.zocdoc.com/about/careers-list/...` returns HTTP 403 with `x-datadome: protected` and a captcha challenge page; this is explicit bot-blocking and should be honored, not bypassed.
- **F12** — live Tavily probe — `https://builtin.com/job/...` extracts successfully and returns full posting content; Tavily works for this source.
- **F13** — `pyproject.toml` dev dependency list — `playwright>=1.62.0` is present but unused in `src/` or `tests/`; it is a potential bypass mechanism for bot-blocking, but the operator's position is to honor bot-blocking, not work around it (→ operator, F11).
- **F14** — operator — the ideal of resolving failures up front without a manual posting loop is not achievable for these cases: Workday JS-apps require a rendering engine, and Zocdoc uses explicit anti-bot protection; the practical path is graceful degradation plus durable failure records, with a manual posting fallback as a future, separate feature.
- **F15** — Tavily response shape — Tavily collapses distinct underlying causes (404, 403, JS-rendered page, timeout) into the same generic `failed_results[].error: "Failed to fetch url"`, so the dispatcher cannot rely on fine-grained classification from the API alone; classification must be coarse or require an extra HTTP probe that would itself be brittle and potentially blocked.
