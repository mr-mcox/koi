---
feature: dimension-digest
type: scouting
date: 2026-08-29
commit: 1c109aedd1aff28d690a115ae7148c4706ad3e1a
parent: ./digest-latency-and-style.md
---

## What We're Doing

Polish the digest experience: stop paying for generation on the rating view, make the prompt produce shorter, scannable output, and render any formatting it returns. Operator's framing: clicking "rate" from the queue shouldn't wait 20s for digests; the current digest is almost as long as the assertion it's summarizing; em-dashes hurt readability; bullets/short phrases would help, but only if word count stays short.

## Findings

- **F1** — `src/screen/web/routes.py:145` — `_dimension_groups` calls `digest_for_target` synchronously; a cold cache means the rating view blocks on live model calls.
- **F2** — `src/screen/baml_src/digest.baml` — the prompt asks for "a single scannable sentence (two only if the evidence genuinely needs it)" but does not enforce a word budget, forbid em-dashes, or invite bullet fragments.
- **F3** — operator — current digests are too long to scan; wants short phrases, hierarchy, bullets, and formatting, but never at the cost of brevity.
- **F4** — `src/screen/web/templates/rating.html:15` — the digest is rendered as a plain `<p>`; line breaks and bullets are collapsed.
- **F5** — `src/screen/digest/service.py` — `digest_for_target` exists for one target; no helper warms all targets for an opening at once.
- **F6** — `src/screen/intake/cli.py:249` / `src/screen/research/dispatcher.py:53` — `dispatch` returns a `PassSummary`; the CLI is the natural place to hook post-pass digest warming.
- **F7** — `src/screen/digest/service.py` — staleness is keyed by assertion count, so warming at the end of a pass is exact and idempotent until new assertions arrive.
