-- Pipeline stage (opening-lifecycle bearing, domain-model.md §Opening):
-- screening | pursuing | applied | closed. `NOT NULL DEFAULT 'screening'`
-- backfills every existing row into the live queue unchanged.
ALTER TABLE openings ADD COLUMN stage TEXT NOT NULL DEFAULT 'screening';
