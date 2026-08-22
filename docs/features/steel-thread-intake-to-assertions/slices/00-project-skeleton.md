---
feature: steel-thread-intake-to-assertions
slice: 00-project-skeleton
date: 2026-08-22
commit: 7ec8252
branch: main
status: solution-space
parent: ../brief.md
scouting: ../scouting.md
---

## Problem

The repo cannot run as a package yet: no `pyproject.toml`, no `src/sceeen/` package,
no `tests/` directory, no `.env.example`, no `.gitignore` for the data directory
or secrets. This slice lands the *minimum* layout so subsequent slices have a
runnable substrate to build on.

This is **Slice 0** of the parent epic. It is the only slice whose value is
discipline-of-layout, not visible capability. Every other slice will create files
into a shape that already exists here.

## Done When

- [ ] `python -m sceeen --help` exits 0 with a short usage line.
- [ ] `pytest` runs and reports "no tests ran" (or any number of tests added) with no
      network calls and no missing imports.
- [ ] `pyproject.toml` declares Python ≥ 3.11, `pydantic >= 2.0`, and `pytest` as
      runtime + dev deps. **BAML and Tavily are NOT installed yet** — they land in
      the slice that introduces them. Adding them here is a boundary violation
      because we would be installing capabilities before they're exercised.
- [ ] `src/sceeen/__main__.py` exists and contains only an argparse-styled `--help`
      reachable through `python -m`.
- [ ] `src/sceeen/__init__.py` exists (empty).
- [ ] `tests/` directory exists with `tests/__init__.py`, `tests/conftest.py`, and at
      least one passing test asserting the importable package layout.
- [ ] `.env.example` exists with placeholder keys (`TAVILY_API_KEY=`,
      `OPENAI_API_KEY=`) — both will be used later.
- [ ] `.gitignore` contains `data/` and `.env` (the two `.gitignore` lines the parent
      brief already calls for).
- [ ] No committed file contains a real company name, salary figure, or résumé text.

## Inherits From Parent

- **Scouting**: file-shape, stack, provider direction, CLI, config, rubric, tests —
  all inherited.
- **Constraints** from the parent brief that apply *here*:
  - Python, Pydantic, Tavily-named-via-`.env.example`.
  - Repository layout convention: `pyproject.toml` is the sole dependency declaration,
    `src/sceeen/__main__.py` is the CLI entry.

Constraints inherited but **not exercised in this slice** (they activate when
their owning slice starts): rubric, BAML, agent loop, transcript, walls, four-state
model, dispatcher. They are not in tension with this slice because this slice
introduces *no* behavior for them to constrain.

## Not Doing

- **BAML installation** — that lands in Slice 2 when first BAML function is needed.
- **Tavily client installation** — that lands in Slice 1, the first slice that uses
  Tavily. The placeholder key in `.env.example` is fine because `.env.example` is
  a *template*, not a config.
- **Any domain type (Company, Opening, Assertion, LoopState)** — Slice 2 introduces
  Company/Opening; Slice 3 introduces Assertion. Batting this slice first lets
  schema evolve with BAML feedback.
- **rubric.yaml** — Slice 3 (first place assertions are scored against it).
- **`.env` actually populated** — happens from Slice 1 onwards when a real run is
  needed.

## Explicit "We picked this over that" choices

These get logged in `decisions.md` rather than buried here:

- **Layout: `src/`-layout, not flat-layout.** `src/sceeen/` is the conventional
  Python packaging layout. Avoids accidental imports from the repo root and keeps
  `tests/` cleanly separated from production code. **Alt**: flat layout with
  `sceeen/`. Rejected because flat layout has historically caused test imports
  to silently resolve to local modules instead of installed code.
- **Build system: `uv` (where present), pip-fallback pyproject.** `uv` is on this
  machine; `pyproject.toml` only declares deps, letting either tool resolve them.
  No `pyproject.toml` build-system pinning that would diverge between tools.
- **Python floor: 3.11.** Pydantic v2 needs ≥ 3.8; Pydantic AI (in case we ever
  revisit) suggests 3.10; BAML has no constraint beyond "modern Python." Picking
  3.11 gives us the modern type feature set `Literal[k:v]` ergonomics without
  committing to bleeding-edge 3.14 — important because the operator has multiple
  machines and may not be on 3.14 everywhere.

## Out-of-scope decisions (no decision needed yet)

- Test directory partition (`tests/walls/`, `tests/prompts/`, `tests/dispatch/`,
  `tests/integration/`) — Slice 2+ introduces these. Today `tests/` is flat.
- Whether the project is installed editable or via `pip install .` — Slice 1
  decides (first slice that runs a real command against the package).
- BAML codegen target language (Python + Pydantic) — parent constraint, no
  Slice-0 surface.

## Why this slice is the smallest possible

The shape it introduces is a *tax*, not a feature. Shrinking further would mean
either:

- No `pyproject.toml` yet (then Slice 1 has to invent the layout itself,
  violating "tests exist before the wiring").
- No `__main__.py` (then `python -m sceeen` cannot be verified to work, and Slice 1
  inherits the verification gap).

So the layout must exist before any other slice starts.

## Testing

- **Test-first**: write `tests/test_layout.py` asserting
  - `python -m sceeen --help` runs cleanly.
  - `import sceeen` succeeds (importable package).
  - `.env.example`, `.gitignore`, `pyproject.toml` exist.
  - `.gitignore` content contains both `data/` and `.env`.
  - `.env.example` contains `TAVILY_API_KEY=` (placeholder format).
  - Run the test, paste the failure, write the layout, paste the success.
- **Test-after**: nothing else; the layout test is the only thing this slice
  earns.
- **None**: trivially specific to internal helpers (none exist yet).

## Decisions to Log in `decisions.md`

(`decisions.md` does not exist yet; this slice creates it.)

- 2026-08-22 — `src/sceeen/` package layout with `pyproject.toml` PEP 621 metadata.
- 2026-08-22 — Python floor at 3.11, not 3.14.
- 2026-08-22 — BAML and Tavily Python client deferred to their owning slices; this
  slice's `pyproject.toml` is intentionally lean.

## Escalation Triggers

- If `uv` is not available on the operator's machine and they want pip-install-only:
  drop the `uv` mentions but keep the `pyproject.toml` shape.
- If a project layout other than `src/sceeen/` is already in this repo: stop.
  Renaming a layout mid-feature is a renaming of every future file.
