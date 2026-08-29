-- Cached LLM-generated prose digest of a dimension's assertion mix.
-- Additive only — no change to companies/openings/assertions (F7).
-- `assertion_count` is the staleness key: assertions are append-only (wall 6),
-- so a monotonic count comparison against the current count for
-- (opening_id, target) is exact and sufficient to detect staleness (F5, F6).
CREATE TABLE dimension_digests (
    opening_id TEXT NOT NULL REFERENCES openings (id),
    target TEXT NOT NULL,
    digest TEXT NOT NULL,
    assertion_count INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (opening_id, target)
);
