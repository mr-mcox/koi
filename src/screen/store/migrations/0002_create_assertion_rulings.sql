-- Sibling to `assertions`, not a column on it (F25/F28): an AssertionRuling is the
-- operator's own confirm/override record, kept separate so the model's proposal is
-- never overwritten in place (Wall 6 applies to Assertion; this table is append-only
-- for the same reason a ruling supersedes rather than mutates).
CREATE TABLE assertion_rulings (
    id TEXT PRIMARY KEY,
    assertion_id TEXT NOT NULL REFERENCES assertions (id),
    fit TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_assertion_rulings_assertion_id ON assertion_rulings (assertion_id);
