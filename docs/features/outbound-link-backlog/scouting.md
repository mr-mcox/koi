---
feature: outbound-link-backlog
type: scouting
date: 2026-11-03
commit: aa6b3ab
---

## What We're Doing

Split out of `research-target-opportunity` (that report's F17). The operator's framing,
from that report's original problem statement: when a fetch reveals promising outbound
links, keep them as a backlog the planner can revisit later by URL, "instead of forcing the
pass to strike gold immediately", so a page with several useful links can keep yielding
follow-up fetches without a new search every turn. The action vocabulary stays `search`,
`fetch`, `stop`, so visiting a backlog link is just a `fetch`.

Sequenced **after** `research-target-opportunity`: link relevance is judged against the
current research question, which that feature introduces.

## Findings

- **F1** — `src/screen/research/dispatcher.py:304` — the only part of a fetched page the
  planner ever sees is `raw_content[:500]`, stored as `FetchContext.snippet`
  (`src/screen/research/context.py:28-40`, whose docstring says "enough for link spotting").
  Links past character 500 are invisible to the planner, today and on every later turn.
- **F2** — `src/screen/research/baml_planner.py:34-57` — `last_context_text` renders only the
  **immediately previous** action. After one more action, a fetched page's snippet (and any
  links in it) drops out of the prompt for good. This is the operator's problem: a link
  stays visible for exactly one turn.
- **F3** — `src/screen/research_trace/events.py:83-97` — every successful fetch's full
  `raw_content` is already persisted in the trace as `ExtractResult`. A backlog can therefore
  be **derived on replay** from existing traces, with no new trace field and no migration
  (decisions E8): parse links out of each stored `raw_content`, minus `visited_urls`.
- **F4** — `src/screen/browser.py:118-123` — fetches go through Tavily `extract` with
  `extract_depth="advanced"` and no `format` argument. The installed SDK's signature accepts
  `format: 'markdown' | 'text'`, plus `query` and `chunks_per_source`, all unused. If the
  content isn't markdown, anchor text and URL may already be separated or stripped, which
  decides whether "the visible text that made the link worth keeping" is recoverable.
- **F5** [x] — measured on `data/live/research_traces/` (read-only, operator-permitted 2026-11-03), 632 fetched pages: links are present as **markdown `[text](url)`**, with deciles of markdown links per page `1, 4, 8, 13, 24, 47, 57, 98, 166` (mean 53). 17 pages had no URL at all. Anchor text is therefore recoverable from stored content, and the feature is "parse what we have", not "change how we fetch" (F4 is moot). Original question: do stored `raw_content` bodies actually contain links, and in
  what form** (markdown `[text](url)`, bare URLs, or none)? The scratch DB's one trace has
  no extract result with content, and `data/live/` is off-limits to agents (AGENTS.md
  §Data). Settled by: the operator running a link-count over live traces, or one scratch
  intake against a synthetic page. This decides whether the feature is "parse what we
  have" or "change how we fetch" (F4).
- **F6** — `src/screen/baml_src/research.baml:42-100` — the prompt already tells the planner
  to skip navigation/home/contact/login/social links and prefer links that address the
  target. Five smoke tests (`:109-196`) cover choosing a link out of a snippet. Relevance
  filtering is already a model job, and the backlog only needs to keep candidates visible.
- **F7** — decisions W7 (`intake/admission.py`) — hosts that refuse automation are blocked at
  submit, and W7 notes "the research planner has never once followed an aggregator link."
  Backlog entries pointing at refused hosts would be dead weight, so filtering against the
  same list is a candidate (open space).
- **F8** [ ] — operator — what makes a link "promising" enough to keep: (a) every
  non-navigation link on the page, filtered deterministically (cheap, noisy); (b) the
  planner, or the extractor, nominates links per fetch (one more model output field, so
  judgment is recorded in the trace); (c) all links, with ranking left to the planner at
  read time. Note the parent feature just loosened "`DecidePlan` is the only LLM-shaped
  decision", so (b) adds an output field, not a new call.
- **F9** [ ] — operator — backlog size bound and ordering. A hub page can carry hundreds of
  links. Prompt size is the recalibration risk the parent bearing named ("a structured link
  backlog proves too brittle … without widening the prompt again").
- **F10** — `src/screen/research_trace/replay.py:17-30,128-149` — `TraceReplay` is where
  resumable state is already folded out of the trace (`visited_urls`, `prior_queries`,
  `target_stalls`). A derived backlog would sit beside those. Because each batch block
  resumes from replay (`src/screen/research/batch.py:170`), backlog links persist across
  passes on the same opening, not just within one pass.
- **F11** — `docs/features/research-target-opportunity/scouting.md` F20 — research questions
  are chosen once per opportunity and change between passes. A link kept under one
  question may be irrelevant to the next. Whether backlog entries carry the question that
  harvested them is an open shape question to settle in this feature's bearing.
- **F12** — live traces (same measurement) — of 532 planner fetches, **9 (1.7%) followed a link seen on a previously fetched page**, and 482 (91%) were search hits. Meanwhile 542 of 632 pages had at least one URL inside the 500-char snippet the planner sees (F1). Links are visible but almost never followed, so the fix may be prompt-side or a visibility issue as much as a persistence issue. This is the baseline any backlog has to move (parent bearing's Recalibrate: "if outbound-link backlog visibility does not improve follow-through").
- **F13** — `docs/features/research-target-opportunity/scouting.md` F34 — fetches yield about 50% and searches about 4%, so a fetch that skips a search step is worth roughly one turn. That's the value a backlog would capture.
