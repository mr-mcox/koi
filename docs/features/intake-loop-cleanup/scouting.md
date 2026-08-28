---
name: intake-loop-cleanup
feature: intake-loop-cleanup
type: scouting
date: 2026-08-28
provenance: surfaced during review-shell session; operator flagged terminology drift and misplaced resumability substrate
---

# Intake / Loop Cleanup — Scouting

## Problem

The names and physical layout of the intake-to-research pipeline no longer describe what the code does. The drift is producing real friction (operator ran `uv run python -m screen <url>` and expected it to land in the live DB; the actual issue was invocation, but the naming made it harder to see what writes where). More importantly, a load-bearing concept — *resumability* — has been assigned to the wrong artifact, and a file-level invariant is being stated as if it were architecture.

## What we found

- **F1** — `src/screen/intake/cli.py:166-188` — `_identify_transcript` does not identify. It reads a transcript, derives Company + Opening, opens the DB, persists both, extracts and persists Assertions, and runs the full dispatch/research loop. The name describes ~10% of the function.
- **F2** — `src/screen/intake/cli.py:138-163` — `_fetch_url` does fetch a URL, but its return value is a *transcript path*, not page content. The seam is written around a disk artifact, not around the data that changes hands.
- **F3** — `src/screen/intake/transcript_io.py:1-6` — the docstring claims "Wall 6: transcript append-only invariant" and says "a future replay command depends on a transcript whose bytes have not been rewritten since first write." No such replay command exists, and no ratified decision (E5 in `decisions.md`, the `ResearchPass` contract) says the transcript file is the append-only ledger. The invariant is self-claimed, not architecture-backed.
- **F4** — `src/screen/intake/transcript_io.py` + `src/screen/intake/events.py` — "transcript" is a JSONL event log of raw tool calls (`tavily_extract`, `tavily_search`, `decide_plan`). That is not the same as the typed, provenance-carrying evidence in `Assertion` rows. Conflating the two is exactly the drift: the file is a raw trace, the DB is the evidence ledger, but the word "transcript" is being asked to do both jobs.
- **F5** — `src/screen/loop/state.py:17-41` — `LoopState` already treats `visited_urls`, `prior_queries`, `searches_used`, `tokens_used` as per-pass working values, not persisted facts. This is consistent with the real resumability state living here (or in a future `ResearchPass` DB record), not in the raw JSONL trace.
- **F6** — `docs/features/review-ux/scouting.md:F7` — operator: "research state should be *computed*, not stored... if we effectively save the transcript, we can resume state at any point." The operator-stated need is resumability; the transcript is only one candidate substrate.
- **F7** — `docs/features/review-ux/scouting.md:F11` — unresolved: the current transcript format has not been verified to carry enough per-target information to distinguish "searched this target, found nothing" from "never attempted." A load-bearing artifact cannot be an unverified one.
- **F8** — `src/screen/intake/cli.py:42-44` and `src/screen/api/app.py:23-24` — `_data_dir()` is duplicated verbatim. Same env var, same default, same logic, two places to drift. The shared root currently covers both `transcripts/` (disk trace) and `screen.db` (DB), which makes the entry point legitimately care about the root — but the code should say that once.
- **F9** — `src/screen/loop/__init__.py` / `src/screen/loop/` — "loop" is itself a weak name. It is a bounded context for the research/dispatch pass (`DecidePlan`, Tavily dispatch, budget enforcement). The operator flagged it as potentially misnamed. Rename candidate: `research` or `pass` or `dispatch`. The API surface inside is mostly about one research pass, not a generic loop.
- **F10** — `src/screen/baml_client/`, `baml_src/` — generated BAML client and source files live inside `src/screen/baml_client` and at repo root `baml_src/`. Their placement was not questioned during this session, but any rename of `loop/` or `intake/` may make the current package layout smell worse. They are part of the same "what is this thing actually called and where does it live" question.
- **F11** — `baml_src/clients.baml:34-38` — `generator target { output_dir "../src/screen/baml_client" }` causes the double nesting: BAML always creates a `baml_client` package inside `output_dir`, so the generated module ends up at `src/screen/baml_client/baml_client/`. To get a single `src/screen/baml_client/` from `src/screen/baml_src/`, `output_dir` must be `..`.

## Operator's reframing (carried into this scout)

- The thing called "transcript" is transient. It is not required to be on disk for correctness.
- There *is* a state piece that the operator wants to be resumable. That may be what "transcript" is trying to be. It can stay on disk for now.
- But it should be named for what it actually is: a raw execution trace / pass log, not a transcript of evidence.
- The eventual target is to bring that resumability state into the DB once there is a real need for resumability. Until then, it stays a file, explicitly marked as interim.

## What the architecture actually says

- `decisions.md` E5 (`adopted`): research is multi-pass and append-only, under an explicit `ResearchPass` contract. It does not say the ledger is a JSONL file.
- `domain-model.md`: `ResearchPass` is assigned targets, budget instrumentation, full trace. The trace is instrumentation; the contract is the durable shape.
- `architecture/README.md` girders: "The dispatcher owns every tool call and all state mutation." That means dispatcher/loop state is the source of truth for a pass, not the JSONL on disk.
- `architecture/README.md` volatile: "Open questions, each stating what would settle it." The choice of resumability substrate is exactly that — volatile until we have a real resumability consumer.

## Not yet settled

- **N1 [x]** — trace name chosen: `research_trace` — will be used for the transient file/log replacing "transcript" (→ bearing §Agreed).
- **N2 [x]** — `loop/` rename chosen: `research/` — will be renamed as part of this cleanup (→ bearing §Agreed).
- **N3 [ ]** — Does the resumability target live in `LoopState` plus a new `ResearchPass` DB table, or in an enriched trace file, or both? Deferred until there is a real replay/resume feature. Operator: keep it a file, explicitly marked interim.
- **N4 [x]** — BAML files move now: `baml_src/` → `src/screen/baml_src/` (sibling to `src/screen/baml_client/`, operator confirmed under `screen` since BAML docs don't dictate otherwise), and the double-nested `baml_client/baml_client` fixed by setting `output_dir` to `..` from the new `baml_src/` (→ bearing §Agreed).

## What a bearing might do

1. Rename functions in `intake/cli.py` to match responsibilities: e.g., `_fetch_url` → `_fetch_posting` returning page content, `_process_opening` or `_run_intake_pass` for the current `_identify_transcript`.
2. Rename "transcript" to the chosen trace name everywhere (file names, function names, `transcript_id.py`, `transcript_io.py`, `events.py` model names).
3. Remove the self-claimed "Wall 6" invariant from the trace module; replace it with an honest comment: *append-only trace file, interim resumability target, not the evidence ledger*.
4. Collapse `_data_dir()` into one shared helper.
5. Optionally rename `loop/` to the chosen name and update imports (a larger, but mechanical, change).
6. Leave the actual DB-resumability design as a follow-up scout/bearing triggered by a real replay/resume feature, not by this cleanup.

## Related

- `docs/features/review-ux/scouting.md` F7, F8, F9, F11, F12 — research-state/resumability discussion.
- `docs/architecture/decisions.md` E5 — the `ResearchPass` contract that is actually ratified.
- `docs/architecture/domain-model.md` — `ResearchPass` entity description.
- `docs/architecture/README.md` — girder list; none of them name the transcript file as load-bearing.
