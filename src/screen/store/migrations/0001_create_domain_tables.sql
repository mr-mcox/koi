CREATE TABLE companies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE openings (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies (id),
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    transcript_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_openings_company_id ON openings (company_id);

-- `opening_id` is a mapper-level column, not a field on `screen.types.Assertion` —
-- the domain model has no notion of physical storage; the directory an assertion's
-- JSONL line lived in was this same foreign key, implicit rather than explicit.
CREATE TABLE assertions (
    id TEXT PRIMARY KEY,
    opening_id TEXT NOT NULL REFERENCES openings (id),
    target TEXT NOT NULL,
    fit TEXT NOT NULL,
    provenance TEXT NOT NULL,
    chunk TEXT NOT NULL,
    citations TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_assertions_opening_id ON assertions (opening_id);
