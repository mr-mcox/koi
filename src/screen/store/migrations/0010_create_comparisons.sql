-- Pairwise operator comparisons between two openings on one dimension.
-- Append-only: every judgment is kept, never updated or replaced. The batch fit reads the
-- latest per (unordered pair, dimension); the calibration log keeps them all regardless.
--
-- `opening_a_digest_version`/`opening_b_digest_version` are nullable placeholders: they
-- reference `dimension_digests` rows once that table becomes append-only; until then both
-- stay NULL.
CREATE TABLE comparisons (
    id TEXT PRIMARY KEY,
    opening_a_id TEXT NOT NULL REFERENCES openings (id),
    opening_b_id TEXT NOT NULL REFERENCES openings (id),
    target TEXT NOT NULL,
    outcome TEXT NOT NULL,
    predicted_a_beats_b REAL NOT NULL,
    opening_a_digest_version TEXT,
    opening_b_digest_version TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_comparisons_target ON comparisons (target);
CREATE INDEX idx_comparisons_openings ON comparisons (opening_a_id, opening_b_id);
