---
feature: steel-thread-intake-to-assertions
type: feature-brief
date: 2026-08-21
commit: 7ec8252
branch: main
status: parent-epic
parent-of: ./slices/
scouting: ./scouting.md
---

## Problem

Ship the first slice of the steel thread — the thinnest possible vertical cut proving our
three novel decisions work (company/opening split, provenance-as-variance, research-pass
contract) before anything layers on. URL in, typed Assertions out; backend only; flat
files instead of a database; no UI. This is the slice that, when it runs end-to-end on
one real opening once, earns the right to scale up.

Terrain: [scouting.md](./scouting.md). S-decisions governing this work live in
`docs/agent-briefs/DECISIONS.md` (S8, E4, E5, R4, D23, D24); entity definitions in
`docs/agent-briefs/DOMAIN-MODEL.md`.

## Done When

- [ ] `python -m sceeen <url>` reads the operator's intake URL, runs the agent loop, and
      writes `data/<company-id>/company.json`, `data/<company-id>/openings/<opening-id>.json`,
      and `data/<company-id>/openings/<opening-id>/assertions.jsonl` — the directory path
      is gitignored, the schema is in this brief.
- [ ] Every output assertion passes `pydantic` validation including a structural check
      that `provenance` constrains `target` to one of the rubric dimensions or explicit
      `non_scoring` markers (Wall 3, invariant: non-scoring targets never enter standing).
- [ ] **Transcript determinism, not byte-identical-assumption**: replaying a recorded
  `transcript.jsonl` through the extraction step regenerates assertions (Shape A is
  live; Shape B is the recorded-trajectory replay). Two CLI runs on the same URL produce
  identical Assertions iff Tavily returns identical responses — transcript variance is
  recorded, not erased. Tests on the agent's *judgment* (action selection, state
  transitions) are behavior-shaped with structural wiggle — tested across action
  categories and state shapes, not against literal text. The brief's invariant: a model
  upgrade or vendor change should not break the test suite.
- [ ] The agent's tool calls and intermediate state are recorded in
      `data/<company-id>/openings/<opening-id>/transcript.jsonl`; replaying the transcript
      through the extraction step regenerates the same assertions without re-calling Tavily
      (Shape B is a replay, Shape A is the live path; the transcript is the connective tissue).
- [ ] `pytest` runs the full test suite in under 30 seconds with no network calls
      (Tavily is mocked; recorded fixtures are the inputs).
- [ ] Domain walls (DOMAIN-MODEL invariants 1, 2, 3, 6) have at least one structural test
      each. Wall 1 / 2 (raw positions never reach scorer, fit and provenance never blend)
      are partially testable here — Scorer is out of scope, so they live as compile-time
      checks on the artifact schema (no field on Assertion that could carry a "blended
      score") rather than runtime assertions.
- [ ] `.env.example` lists every required secret; `.gitignore` contains `data/` and `.env`.
      No committed file contains a real company name, salary figure, or résumé content.

## Slice Map

Implementation splits this epic into smaller vertical-slice briefs under `./slices/`.
Each child brief inherits the parent's scouting + constraints unless it explicitly
narrows them; no fresh scouting. The full URL → typed Assertions pipeline is built
bottom-up, capabilities one at a time, so each child lands a runnable behavior and
its own tests before the next starts.

**Universal principle**: any visible capability appears in its own slice. BAML does
not land on top of an existing chunking system — it is the source of the first BAML
function we ship (Company/Opening identification), and from there we add judgment
and one action per cycle.

| # | Slice                                           | Visible behavior                              |
|---|-------------------------------------------------|-----------------------------------------------|
| 0 | Project skeleton + deps                         | `python -m sceeen --help`, `pytest --collect` |
| 1 | URL + Tavily transcript                         | `data/<id>/transcript.jsonl` written from fetch |
| 2 | BAML identify Company + Opening                 | `company.json` + `opening.json` persisted     |
| 3 | BAML extract assertions from one chunk          | First real rows in `assertions.jsonl`        |
| 4 | Dispatcher skeleton + `[stop]`                  | BAML Dec:dePlan returns `[stop]` end-to-end    |
| 5 | Action capabilities, one per cycle              | `[extract_page]`, `[produce_assertion]`, …    |
| 6 | Replay path                                     | `transcript.jsonl` regenerates assertions    |

Within Slice 5, action types are added **one at a time, smallest first**: `[stop]`
is the only action initially; `[extract_page]` joins it; then `[produce_assertion]`;
finally `[search_more]`. Each cycle ends with the dispatcher actually running a
plan containing that action, with a transcript entry and a passing test.

A `transcript.jsonl` is durable from Slice 1 onwards — once written, it is the
connective tissue for replay (Slice 6) and for any future compare/across-vendor
workflow. The file is append-only and never rewritten outside of legitimate
recovery tooling.

## Not Doing

- **Scorer, standing, queue, ranking, bands** — this slice produces Assertions only. The
  Scorer is the second slice (out of scope here even though the brief invites thinking
  about it).
- **Multiple openings per company** — flat-file schema must not preclude it, but only one
  opening per run is exercised in this slice.
- **Reopening nominations and rubric-feedback routing** — Inbox's work (E5's contract
  has them but they're separately addressed).
- **Operator review flow** — the file artifact is human-greppable; no review tool is
  built. The operator viewing assertions.jsonl with `less` counts as review for now
  (LEARNINGS Q1: prototype's first review was reading the file).
- **Pydantic AI / LangChain / hand-rolled agent framework** — explicitly rejected
  during drafting in favor of BAML-only. Tavily is dispatched by the runner, not by an
  LLM tool-call loop; agent frameworks' tested value-add collapses to nothing once
  tool calling is out of scope. The rejection reason lives in the brief's Constraints
  section below.
- **Persistence beyond flat files** — schema is migration-shaped (separate Company /
  Opening / Assertions files cross-linked by ID) but nothing about the slice should require
  a DB to be considered done.
- **A multi-pass loop in this slice** — one pass, all tools, agent decides loop-control;
  the question of "how many passes does a decision take" (OPEN-Q11) is a deliberately
  deferred measurement, not a feature of this slice.

## Constraints

- **Python, Pydantic, BAML, Tavily, pytest.** Stack is set ([scouting.md §Open
  questions](scouting.md)). Pydantic and BAML together because BAML's `--client-type
  python/pydantic` generates Pydantic v2 BaseModels from `baml_src/`; domain types live
  in one place. No additional agent framework, LLM SDK, or HTTP library without an
  escalation. Operationally, BAML replaces both Pydantic AI's structured-output surface
  and its test scaffolding (rejected during drafting because Tavily is dispatched, not
  agent-called — see Constraints).
- **Repository layout, anchored:**
    - `pyproject.toml` — sole dependency declaration.
    - `src/sceeen/__main__.py` — CLI entry (`python -m sceeen <url>`).
    - `src/sceeen/intake/` — URL → Company + Opening creation (the Intake bounded context).
    - `src/sceeen/loop/` — the deterministic dispatcher (hand-written). Owns Taurily
      calls and state mutation. `decide_plan(state)` is the only LLM-shaped function and
      it is a BAML call from here.
    - `src/sceeen/extract/` — BAML function for typed-extraction (Assertion emission).
    - `baml_src/` — BAML source for both `DecidePlan(state) -> [Action]` and
      `ExtractAssertions(chunk, rubric, existing) -> Assertion[]`. The CLI generator's
      `--client-type python/pydantic` produces `src/sceeen/loop/baml_client/`; that
      directory is generated, not hand-written.
    - `src/sceeen/types.py` — hand-written domain types that are NOT covered by BAML:
      `Company`, `Opening`, `Rubric`, `LoopState`, `Budget`, configuration objects, and
      the recorded `transcript.jsonl` Pydantic model. Imported by extract/ and loop/.
    - `src/sceeen/config.py` — operator-owned configuration (compensation baseline,
      résumé path, search budget, token budget — read from `.env`, never logged).
    - `baml_src/` — BAML source for the Assertion extraction function (co-located with
      project root per BAML convention).
    - `rubric.yaml` — committed rubric (dimension names, definitions, weights); matches
      `docs/agent-briefs/DECISIONS.md` R4.
    - `tests/` — pytest. `tests/walls/` for invariant checks; `tests/integration/` for
      replay-from-transcript tests; `tests/fixtures/` for recorded Tavily responses.
    - `data/` — gitignored, the runtime artifact directory.
- **Artifact schema cross-linked by ID** (separate files per entity, JSON for Companies /
  Openings, JSONL append-only for Assertions). The rejection of one-file-per-Opening (option
  a in scouting) is on record because it duplicates Company evidence on second req.
- **Domain models frozen** (DOMAIN-MODEL walls 1, 2, 3, 6) — asserting these structurally
  on the schema:
    - Wall 1 / 2: `Assertion` has separate `fit` and `provenance` fields with `provenance`
      *not* present in any computed form. Compile time: no Pydantic field on any output
      type named `score`, `confidence_score`, `weighted_score`, or similar.
    - Wall 3: `Assertion.target` is a Literal over a closed set; non-scoring targets are
      a separate Literal. A test walks every Assertion row and asserts target ∈ scoring
      targets OR target ∈ non_scoring_targets — never in both, never in neither.
    - Wall 6: Assertions append-only — the file is opened only in append mode after first
      write in any pass.
- **Agent returns a plan, dispatcher executes it.** `DecidePlan(state) -> [Action]` is a
  BAML function (`baml_src/agents.baml`); the dispatcher in `src/sceeen/loop/dispatch.py`
  calls it with the current `LoopState`. The BAML function returns an ordered plan of
  typed actions, each ∈ {`search_more`, `extract_page`, `produce_assertion`, `stop`}.
  Multiple actions per call are normal — extracting several pages, producing multiple
  assertions, and adding a follow-up search in one plan is the expected shape.
  - The dispatcher owns *all* tool calls and state mutation. Tavily is dispatched by
    the runner based on the plan, never called by an LLM.
  - Stops and budget checks fire between plan elements.
  - The boundary: every action handler in `dispatch.py` is a pure function of
    `(state, action) -> (new_state, tool_outputs)`.
  - This is Shape 1 (judgment-agentic, dispatch-deterministic) from the architectural
    decision. Shape 2 (agent-calls-tools-inline) was rejected because the four-state
    model (findings, useful_context, raw_unread, discovered_urls) only holds together
    when the runner owns tool side effects.
- **Tavily is the search provider.** Key in `.env`. Single point of integration is
  `src/sceeen/intake/search_client.py`, which exposes `search(query) -> list[URL]`
  and `extract(url) -> PageContent`. Tests mock at this boundary.
- **Two BAML functions, two LLM-shaped responsibilities:**
    - `DecidePlan(state: LoopState) -> list[Action]` — judgment. Reads a serialized
      state JSON, returns an ordered plan.
    - `ExtractAssertions(chunk: PageChunk, rubric: Rubric, existing: list[Assertion])
      -> list[Assertion]` — typed output (Wall 1/2 enforcement: fit and provenance
      are separate fields; provenance never numerical on the codegen output).
  Both BAML calls live behind a thin wrapper in `src/sceeen/loop/baml_client/` so
  tests can substitute recorded-response fixtures at the wrapper boundary.
- **Injectable client contracts.** Real Tavily client and BAML-generated client sit
  behind Protocol-style interfaces in `src/sceeen/clients/`. Tests use fakes/recorded
  responses; production uses real clients. `tests/conftest.py` sets
  `BAML_ALLOW_MODEL_REQUESTS=False` globally so any accidental LLM call in CI fails
  fast with a loud error.
- **Provenance ladder** (S8): four rungs, in this order, each modeling wider noise:
  `unexamined` (max variance) → `model_proposed` → `precedent_matched` → `ratified`
  (narrowest, not zero). The widths-per-rung are CALIBRATION DATA (OPEN-Q1); set to seed
  values, do not tune in this slice.
- **Rubric text is load-bearing** (R4): every dimension's full text is used verbatim in
  the BAML extraction prompt. The extraction prompt is a generated function of
  `rubric.yaml`, not a freeform string.
- **Recorded transcript is the test substrate.** Every tool call and its result lands
  in `transcript.jsonl`. Tests replay the recording without re-calling Tavily; this is
  also what makes Shape B (defer-and-extract) a cheap refactor if Shape A's "premature
  assertion" pain materializes.

## Testing

Five distinct test layers, each with its own discipline:

1. **`tests/walls/` — wall structural tests.** Test-first. Schema assertions on BAML's
   generated Pydantic types: no `score`/`weighted_score` field exists on any codegen;
   `Assertion.target` Literal ∉ both scoring and non-scoring sets; assertions file is
   always opened in append mode after first write. Written before any other code.
2. **`tests/prompts/` — BAML prompt tests.** Test-first. `baml test` invokes each BAML
   function against golden inputs (hand-transcribed from a real prototype run on a
   data-equivalent — *synthetic*, never committed PII). Verifies the prompt contract:
   given this state → produces this plan; given this chunk + rubric + existing →
   produces these assertions.
3. **`tests/dispatch/` — dispatcher state-transition tests.** Test-first. Parametrized
   over `(state, action) -> (new_state, tool_calls)` pairs. Pure-function tests of the
   action handlers; no Tavily call, no LLM call.
4. **`tests/integration/` — transcript-replay integration tests.** Test-after. Replays
   a recorded `transcript.jsonl` (containing canned Tavily responses) through the real
   dispatcher with BAML prompt tests as the mocking layer. Tests the seam between
   dispatcher prompts and tool-output handling.
5. **CI guard — `tests/conftest.py`** sets `BAML_ALLOW_MODEL_REQUESTS=False` (or
   BAML's equivalent flag) so any accidental live model call fails fast. Also: a single
   static rubric-prompt-equality check.

**Test-after**: low-level internal helpers, glue code, CLI argparse wiring.

**None**: deliberate exemption is real test cost, not test orchestration. If a layer
can't be tested cheaply, that's a design smell, not a testing exemption.

## Escalation Triggers

- If the dispatcher wants to call a tool outside `{tavily_search, tavily_extract,
  internal_chunk, append_assertion}` — stop. New tools are a vocabulary change.
- If the agent wants to mutate `findings` outside of `produce_assertion` — stop. That is
  the wall, not a guidance.
- If the per-pass cost on a real run exceeds an operator-configured threshold (default
  floor $0.50 / pass, calibrated against a firework-class model on a small search
  load) — surface a warning at run completion, and emit a run-summary line in
  `transcript.jsonl` with tokens and cost. Model identity (provider + model name) is
  operator-owned config; the cost floor is configured at deployment time. The default
  config starts at a firework-tier `~8b-instruct` — the prototype used opus, which was
  overkill.
- If `raw_unread` storage exceeds 50 MB per pass — stop and ask. That's the volatility
  area's lower bound.
- If a `rubric.yaml` field appears that does not appear in
  `docs/agent-briefs/DECISIONS.md` (after checking for stale references) — stop. New
  rubrics are decisions; record them in DECISIONS or escalate.
- If Shape A's "premature assertion" instinct produces noticeably different assertion
  counts on replay versus live runs — re-evaluate Shape B. The replay-vs-live delta is
  the measurement; don't paper it over.

## Decisions

_(empty at approval — full log in decisions.md)_
