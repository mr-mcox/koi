-- The operator's continuous placement for one dimension/opening (domain-model.md
-- §Ruling): "given everything, where am I on this?" Sibling to `assertion_rulings`,
-- not a column on it — different author-intent, different payload shape
-- Keyed (opening_id, target): one pin per dimension per opening, upserted on
-- re-rating, never appended. Pins are not revertable — no path back to unpinned —
-- but resubmission still replaces the value.
CREATE TABLE dimension_rulings (
    id TEXT PRIMARY KEY,
    opening_id TEXT NOT NULL REFERENCES openings (id),
    target TEXT NOT NULL,
    mean REAL NOT NULL,
    settledness REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (opening_id, target)
);
