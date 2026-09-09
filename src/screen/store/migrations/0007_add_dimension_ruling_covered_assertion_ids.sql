-- Snapshot of the assertion ids covered at ruling time — the exact partition between
-- evidence the operator ruled on and anything
-- filed after, used to detect and blend drift. Stored as a JSON array, same convention
-- as `assertions.citations`. `NOT NULL DEFAULT '[]'` backfills every existing row with an
-- empty list; a separate backfill command populates existing rulings from the
-- assertions that existed as of each ruling's `created_at`.
ALTER TABLE dimension_rulings ADD COLUMN covered_assertion_ids TEXT NOT NULL DEFAULT '[]';
