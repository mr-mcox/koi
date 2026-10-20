-- Make dimension_digests append-only with a unique ID and keep history.

CREATE TABLE dimension_digests_new (
    id TEXT PRIMARY KEY,
    opening_id TEXT NOT NULL REFERENCES openings (id),
    target TEXT NOT NULL,
    digest TEXT NOT NULL,
    assertion_count INTEGER NOT NULL,
    computed_at TEXT NOT NULL
);

-- Backfill existing cache entries with a random hex string.
INSERT INTO dimension_digests_new (id, opening_id, target, digest, assertion_count, computed_at)
SELECT lower(hex(randomblob(16))), opening_id, target, digest, assertion_count, computed_at
FROM dimension_digests;

DROP TABLE dimension_digests;
ALTER TABLE dimension_digests_new RENAME TO dimension_digests;

-- Index to optimize getting the latest digest per opening/target.
CREATE INDEX idx_dimension_digests_latest ON dimension_digests (opening_id, target, computed_at DESC);
