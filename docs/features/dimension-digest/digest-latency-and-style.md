---
feature: dimension-digest
type: bearing
date: 2026-08-29
commit: 1c109aedd1aff28d690a115ae7148c4706ad3e1a
branch: main
status: orienting
scouting: ./digest-latency-and-style-scouting.md
parent: ./bearing.md
---

## Problem

The rating view blocks on live digest generation when the cache is cold, and the generated digests are too long and em-dash-heavy to scan quickly. Want: digests warmed by the end of a research pass, a prompt that produces short scannable output with optional bullets/formatting, and a view that renders that formatting. Terrain: [scouting.md](./digest-latency-and-style-scouting.md).

## Done When

- [ ] The CLI warms the digest cache for every target with assertions before the research pass is considered complete
      → `tests/test_cli_intake.py` asserts `FakeDigester` is called after `dispatch` returns
- [ ] `GET /openings/{id}/rate` renders with no live digest calls when the cache is warm
      → `tests/test_web.py` asserts `FakeDigester.calls` is 0 during the request
- [ ] `DigestDimension` prompt enforces ≤30 words, no em-dashes, and uses bullets only for distinct facets or genuine tension
      → BAML smoke test in `src/screen/baml_src/digest.baml`, run outside `scripts/check.py`
- [ ] The rating view renders line breaks and leading-dash bullets in the digest as structured HTML
      → `tests/test_web.py` asserts `<ul>`/`<li>` or `<br>` in the digest section
- [ ] `uv run python scripts/check.py` passes

## Approach

- Add a `update_digests_for_opening` helper to `screen.digest.service` that walks targets with assertions and calls `digest_for_target` for each (→ scouting F5, F7).
- Call that helper from the CLI after `dispatch` returns, before the pass summary is printed (→ scouting F6). Keep it synchronous and post-pass; no async framework or HTMX polling.
- Rewrite `src/screen/baml_src/digest.baml` to include explicit style constraints and a representative smoke test (→ scouting F2, F3).
- Update `src/screen/web/templates/rating.html` to render digest text with line breaks and bullets preserved; no HTML is stored in the digest column (→ scouting F4).

## Not Doing

- No async job framework, background workers, or HTMX polling for cold-cache digests — warming is done synchronously after the research pass.
- No markdown parser dependency; rendering supports only line breaks and leading-dash bullets.
- No operator-authored digest overrides or inline editing.
- No change to the core rubric vocabulary, scoring, or queue view.

## Testing

Test-first by default. Exempt:
- `src/screen/digest/baml_digester.py` — live BAML adapter, no unit coverage by design (same exemption as `baml_extractor.py`).
- The BAML smoke test for style constraints is run with `baml-cli test`, not in `scripts/check.py`.

## Recalibrate When

- Post-pass warming proves too expensive with real openings → stop and consider deferring or async.
- Prompt constraints produce lossy, stilted, or factually wrong digests → relax constraints and revisit.
- Structured rendering degrades readability or introduces unsafe HTML handling → revert to plain text rendering.

## Agreed

- Warm digests after the research pass, not on the first page view (→ scouting F1, operator: 20s wait).
- Bullets and short phrases are allowed only when they improve scanability; em-dashes are forbidden (→ scouting F3, operator).
- Digest storage stays plain text; formatting is a rendering concern only (open space).
