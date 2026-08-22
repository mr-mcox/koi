---
feature: steel-thread-intake-to-assertions
type: scouting
date: 2026-08-21
commit: 7ec8252
status: solution-space
---

## What We're Doing

Slimmest possible slice of the steel thread: paste a URL → system produces typed assertions
at company and opening level. Backend only, flat files instead of a database. The operator
wants to anticipate the general direction without setting up what isn't yet needed, and
is considering going even further upstream — from URL, generate the Company + Opening
entities themselves — rather than assuming those exist first.

## What Exists Now

- `docs/agent-briefs/` — full domain model, decisions, learnings, open questions
- No code, no stack, no directory layout. Zero existing patterns to be wrong about.

## Patterns In This Area

- None established yet. This is the first code.

## What This Would Touch

First code means: whatever we lay down here IS the pattern. The brief needs to commit
to layout and stack choice for the things this slice requires, because those decisions
immediately become the foundation everything else builds on.

## Open Questions

- [x] **Should the slice begin from URL → Company+Opening, or assume Company+Opening exist
  first?** → Operator prefers URL → Company+Opening+Assertions in one shot, unless that's
  trivially bundled. Given the domain model's Intake bounded context, this is the correct
  seam: Intake's job is "the outside world becomes a screenable unit." Starting at that
  boundary is structurally correct, not just convenient.

- [x] **Stack / runtime language?** → Python. Pydantic for domain models. BAML for typed
  LLM output. pytest for test harness.

- [x] **How flat is "flat files"?** → (b) + (c): separate JSON files for Company and
  Opening (cross-linked by ID); append-only JSONL for Assertions per opening. This
  matches the domain model's entity split and is a direct migration path to a DB.

- [x] **Search provider?** → Tavily. Operator has a key (shared with pi).

- [x] **Rubric location?** → Committed YAML (dimension names, definitions, weights).
  Compensation baseline injected from private config at runtime, never committed.

- [x] **LLM provider?** → Intentionally open; want to try several. BAML abstracts
  provider, so this is a named config value, not a code dependency.

- [x] **Runnable artifact?** → CLI. Takes a URL, writes flat files.

- [x] **Private config?** → `.env` file, gitignored. Gitignored `data/` directory for
  flat file output (which contains real company names).

- [x] **Test approach?** → pytest. Domain wall invariants get structural tests. Research
  pass gets integration tests against a fixture (not live Tavily). BAML outputs get
  schema validation tests.

- [!] **Research pass architecture — pi subsession vs. native tool-calling loop.** Operator
  prefers the pi-subsession approach in principle but is open to a native loop if the
  ecosystem has built-in scaffolding worth using. Brief should weigh these options.
  Becomes an escalation trigger in the brief.

  **Options surveyed:**
  1. **Pi subsession → BAML handoff** (the original leaning). Pros: pi handles web
     exploration natively, less plumbing. Cons: pi SDK as runtime dep, handoff file
     becomes a new contract, harder to unit-test exploration, model for exploration is
     pi's, not yours.
  2. **Native Python tool-calling — raw OpenAI function-calling / Anthropic tool-use.**
     Pros: zero framework dep, complete control, fully testable. Cons: you write the
     loop and tool dispatch yourself. Real, but you'd be re-inventing what frameworks
     already solved.
  3. **Pydantic AI agent loop with Tavily** (`pydantic-ai-slim[tavily]`). Pros: agent
     built-in (`Agent(...).run_sync(...)`), `tavily_search_tool` ships out-of-the-box,
     fully testable, first-class Pydantic types, no exotic dependency — and we already
     use Pydantic for domain models. Cons: one more dependency; framework opinions
     re: state/memory may shape future iterations.
  4. **BAML's own tool-use** (baml-agents pattern, `ActionRunner` → `GetNextAction`).
     Pros: BAML also wraps the typed-output step, single mental model for both the
     loop and the extraction. Cons: unmaintained-adjacent (third-party `baml-agents`
     library is "experimental," API version-pinned); BAML's tool-use is a separate
     construct from its structured-output — you'd be using both surfaces.
  5. **smolagents / LangGraph / LlamaIndex Workflows / etc.** — explored and rejected:
     smolagents is the code-emitting agent paradigm (overkill for our constrained tool
     set, and misaligned with our BAML-typed-output habit), LangGraph adds graph
     modeling overhead our three-state loop doesn't need, full LangChain is an opinion
     minefield. Noted for completeness.

  **Lean:** option 3 — Pydantic AI with Tavily's bundled tool. Reuses an existing
  dependency class (Pydantic), Tavily integration is a one-liner, agent loop is built
  in, exploration is testable with mocked tools, and BAML stays where it's strongest
  (the structured extraction step that follows exploration).

## Prior Art

- `docs/agent-briefs/DOMAIN-MODEL.md` — entity definitions, the walls, Intake bounded
  context, the steel thread order
- `docs/agent-briefs/DECISIONS.md` — S8 (provenance-as-variance), E4 (company/opening
  split), E5 (research pass contract, append-only), R4 (rubric text is load-bearing), D23
  (compensation baseline is private)
- `docs/agent-briefs/LEARNINGS.md` — Q3: research pass cost, search cap as spend dial;
  Q1: one full prototype cycle observations
- `docs/agent-briefs/PROTOTYPE-DECISIONS.md` — D1 (SQLite in prototype), D9 (unattended
  research pass via API)
