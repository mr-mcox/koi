---
feature: steel-thread-intake-to-assertions
slice: 01-url-to-transcript
date: 2026-08-22
commit: 7ec8252
branch: main
status: solution-space
parent: ../brief.md
scouting: ../scouting.md
---

## Problem

The repo currently can do nothing visible with a URL. Operators want to drop a
job posting into a CLI and have something durable on disk they can inspect —
*before* any LLM categorizes the company or extracts assertions. This slice adds
the **first runnable capability** of the steel thread: given a URL, fetch and
record what came back. No model in the loop; just Tavily + a transcript.

This slice produces a recorded `transcript.jsonl` that is the connective tissue
for every future slice. Once written, it is **durable**. Slice 6 (replay) and
any future vendor-comparison workflow will read this file, not re-call Tavily.

## Done When

- [ ] `python -m sceeen <url>` creates `data/<company-id>/transcript.jsonl` with at
      least the URL and the initial `tavily_extract` request/response logged.
- [ ] Target directory exists, is gitignored, and contains the company-id derived
      deterministically from the URL (slug or stable hash — pinned in this brief).
- [ ] Tavily call goes through a wrapper in `src/sceeen/intake/search_client.py`,
      behind an interface replaceable with a fake for tests.
- [ ] Tavily Python client (`tavily-python`) is now a runtime dep in `pyproject.toml`.
- [ ] Transcript events are Pydantic-validated. Each event record has at minimum:
      `ts`, `tool` (enum: `tavily_extract`, `tavily_search`), `request`, `response`.
- [ ] `<company-id>` is computed by Tavily's extract response (`extract.metadata`)
      and matched to the URL — when ambiguous, the wrapper applies a deterministic
      fallback (e.g. URL hostname or hash).
- [ ] Tests run in <30s with **zero network**: a fake Tavily client sits in
      `src/sceeen/intake/fakes.py`; tests inject it.
- [ ] At least one test replays a recorded fixture transcript and asserts the
      transcript was rewritten the same way on second pass (replay is read-only at
      this slice; the assertion that "replay reproduces" is checked but live
      re-extraction is not part of Slice 1's job).
- [ ] `.env.example` still lists `TAVILY_API_KEY=` (now actually consumed).
- [ ] No real company names. Tavily fake fixtures use synthetic placeholders
      (`example.com`, "Example Co."); verify before commit.

## Slice Dependency

- **Requires Slice 0** for the layout — `pyproject.toml`, `src/sceeen/`,
  `tests/`, `.gitignore`, `.env.example`. Slice 0's `TAVILY_API_KEY=` placeholder
  is read here.
- **Consumes nothing from future slices** — Slice 1 produces an actual file but
  does not infer Company/Opening names from it. That is Slice 2's job.

## Inherits From Parent

- **Tavily dependency discipline**: one wrapper, one Protocol, one fake.
- **Artifact directory `data/`**: gitignored, deterministic IDs.
- **Pydantic for transcript events** (parent constraint).
- **No real company names anywhere** (parent brief + AGENTS.md privacy).
- **Workspace**: `python -m sceeen <url>` is the CLI shape for every slice (parent
  constraint).

## Not Doing

- **BAML, LLM, or any model invocation.** The transcript records what Tavily
  returned; no extraction happens in this slice.
- **Company / Opening files** (`company.json`, `openings/<id>.json`),
  `assertions.jsonl`. Those are Slices 2 and 3.
- **Dispatcher / LoopState / Action.** Those are Slices 4–5.
- **Re-running or replaying Tavily responses.** Slice 6 wires replay; this slice
  just needs the recording. We can test "the file is the same on second pass"
  if writes are idempotent at the transcript level (open in append only after
  first write), but a real replay test is Slice 6.
- **Multiple openings.** Slice 1 supports one URL = one company slot.
- **`tavily_search` (search-by-query).** This slice uses `tavily_extract` only.
  Search-by-query enters with Slice 5's `[search_more]` action.

## Explicit "We picked this over that" choices

- **`tavily_extract` only, not `tavily_search`.** A job-posting URL is a *page*,
  not a query. `extract` returns the page content directly and is what this
  slice needs to record. Adding `search` here would import decision surface the
  model owns in Slice 5.
- **Transcript file format: JSONL, not JSON array.** JSONL appends cleanly, so
  `assertions.jsonl` later won't need a separate concern (assertions will use
  the same format the brief specifies for them). One file format for
  append-only records is strictly easier to reason about than two.
- **Company-id slug: hostname-or-hash.** Tavily extract returns a `metadata`
  block with title and source URL; if the title is a "Company" name we use
  slugified hostname (deterministic, never written to a commit). When ambiguous
  (e.g. ATS-hosted), we fall back to a SHA-1 of the canonicalized URL. **Alt**:
  always hash the URL — reduces readability but eliminates ambiguity. We use
  hostname-or-hash to prioritize grepability in `data/` directories.
- **Fake Tavily fixture format: JSON in `tests/fixtures/tavily/`** —
  one file per response, named by URL hash, so adding fixtures is just dropping
  a JSON file. The fake client loads by URL hash.

## Out-of-scope decisions (no decision needed yet)

- Transcript event schema — defined *here* in this slice. Stays as-is until
  Slices 3+ need new event types. Don't pre-build for assertion events.
- Retry/backoff for Tavily — Tavily errors are recorded as a transcript event
  with a `tool_error` field, the loop returns the error and the operator sees a
  partial transcript. Robust retry is Slice 5's concern (action layer owns it).
- How chunking happens later (TokenCount? sentence boundary? LangChain-style?)
  — Slice 3's problem.

## Testing

- **Test-first**: `tests/intake/test_search_client.py` — wrapper existence, fake
  fixture loading, deterministic ID computation, transcript write format.
- **Test-first**: `tests/intake/test_cli.py` — `python -m sceeen <url>` produces
  the expected `data/<id>/` structure with a fake Tavily.
- **Test-first**: `tests/walls/test_transcript.py` — Wall 6 (append-only file
  semantics) gets **its first concrete test** in this slice: opening the
  transcript file in `'r+'` or `'w'` mode, after a successful append, raises an
  error or is rejected by a fixture.
- **Test-after**: replay idempotency check (see "Not Doing"; we test that
  re-running the CLI does not duplicate the transcript, but only because
  Slice 0's layout discipline warrants it; we don't enable full replay yet).

## Decisions to Log in `decisions.md`

- 2026-08-22 — Tavily Python client (`tavily-python`) is the real client; tests
  inject a fake through a Protocol boundary.
- 2026-08-22 — Transcript event schema: `(ts, tool, request, response)` Pydantic
  records JSONL. Wall 6 (append-only) gains a first concrete test in this slice.
- 2026-08-22 — Company-id: hostname-slug with SHA-1(URL) fallback for
  ambiguous ATS cases.

## Escalation Triggers

- If Tavily's free tier cannot be exercised on this machine — fall back to
  stop-on-error transcript rather than retry. This is consistent with brief's
  "Robust retry is Slice 5's concern."
- If the `tavily-python` package is not installable on Python 3.14 — flag and
  pause. This slice is on the critical path of every future slice; we don't
  design around an incompatible dependency.
- If Pydantic v2 introduces a schema that requires sibling-Python-version support
  (e.g. `Annotated[... , ...]` requirements) on 3.14 — surface and decide.

## Why this slice is vertical

The argument for "URL → transcript":

- *Without it*, future slices can't run at all — they're testing the loop
  against an empty `data/`.
- *With it*, we have a runnable behavior in 6–9 files: wrapper, fake, Pydantic
  transcript model, CLI arg parsing, idempotency test, missing-network test.
- *It does not constrain* Slice 2/3 design — they read the same
  `transcript.jsonl` regardless of URL handling.
