-- Per-opening lifetime research-turns budget (research-resumability bearing,
-- F23/F25): one flat dial, seeded from scoring.yaml at intake, manually
-- bumpable per opening. `NOT NULL DEFAULT 0` backfills every existing row with
-- 0 so the column is never null; a separate backfill command sets existing
-- rows to the current scoring.yaml value (0 is not a valid operator target,
-- so it doubles as "never seeded").
ALTER TABLE openings ADD COLUMN research_turns_budget INTEGER NOT NULL DEFAULT 0;
