---
feature: queue-staleness
type: bearing
date: 2026-10-19
status: orienting
scouting: ./scouting.md
---

## Context

We want to optimize wall-clock time during a focused compare session by overlapping system work with the operator's reading and judgment time. The existing compare flow already uses background work and a polling status surface (`/compare-status`) for Jev prescreening; this bearing extends that pattern to the human-facing next-comparison handoff.

## Current State

- The live session now speculates on the next comparison while the operator is reading the current one.
- On submit, the speculative result is promoted into the live cache when it matches the comparison that was on screen.
- The next `GET /compare` is typically a stale-by-one cache hit instead of a fresh wait.
- Background Jev prescreening still runs in parallel and can auto-rule easy pairs before the operator sees them.
- Runtime logging is being trimmed back to high-level state transitions; the remaining logs still make the key outcomes visible, and DEBUG can be used when a timing trace is needed.

## Commitments

### 1. Cache the next compare as a versioned hint
We will cache the next compare suggestion in memory alongside the compare-state version that produced it. The cache is a latency-hiding hint, not durable state.

### 2. Accept stale-by-one if the pair is still legal
We will allow a suggestion computed on the current version or one compare write behind to be used on the redirected `GET /compare`, provided the pair/target is still legal under the latest DB state. Anything older than one compare write is too stale and must be discarded.

### 3. Let Jev keep advancing in the background, but validate each commit
The background prescreen path may keep auto-ruling easy pairs while the operator is reading the current one, but each stored Jev ruling must still validate against the latest compare version before commit. If the operator has advanced the pool first, the worker discards that step and restarts from the new state.

### 4. Keep the cache in process, not in SQLite
We will not persist a speculative queue in the database. The live DB remains the source of truth; the speculative compare cache stays process-local and disposable.

### 5. Measure before declaring this a win
We will record cache hit rate, stale-reject rate, and wall-clock time to the next usable comparison. The design only earns its keep if it actually reduces idle time during the operator's review window.

## Not Doing

- Exact freshness on every redirected `GET /compare`
- A full speculative future tree of compare branches
- A new ranking heuristic or a new scoring model
- A durable queue of future comparisons in SQLite

## Recalibrate When

- Stale-by-one suggestions are mostly rejected as illegal
- Background Jev advancement starts fighting the human flow instead of hiding latency
- The measured wall-clock savings do not outweigh the added complexity

## Readback for the three “no …” cases

Yes — they should be obvious:

- **No cache yet** shows up as `compare cache miss: empty`.
- **No legal stale-by-one reuse** shows up as `compare cache miss: just-written-pair`, `too-stale`, `invalid-target`, `degenerate-pair`, or `missing-opening`.
- **No speculative next pair** shows up as the speculation path declining to publish a result; when DEBUG is enabled, that is visible as the speculative pass finding nothing beyond the on-screen pair or discarding a stale result.
