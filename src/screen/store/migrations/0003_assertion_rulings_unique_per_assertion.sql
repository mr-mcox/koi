-- A ruling supersedes rather than accumulates (F26: re-rating is expected, not an
-- event log) — `upsert_assertion_ruling` relies on this constraint for its
-- `ON CONFLICT (assertion_id) DO UPDATE`, one row per assertion, not append-only.
CREATE UNIQUE INDEX idx_assertion_rulings_assertion_id_unique ON assertion_rulings (assertion_id);
