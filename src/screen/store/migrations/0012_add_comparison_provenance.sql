-- Comparison rows get an explicit provenance so provisional ties can be stored alongside
-- operator rulings and weighted differently in the scorer.
ALTER TABLE comparisons ADD COLUMN provenance TEXT NOT NULL DEFAULT 'operator';
