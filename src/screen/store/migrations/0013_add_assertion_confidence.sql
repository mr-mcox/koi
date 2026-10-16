-- Add Jev confidence scores to assertions. Confidence is a calibrated probability (0-1)
-- that measures how certain the classification is. Null for assertions classified before
-- this feature (backward compatible); existing assertions retain their original provenance
-- and default to confidence=1.0 in scorer calculations (maximal confidence, no widening).
ALTER TABLE assertions ADD COLUMN confidence REAL;

-- Index for filtering low-confidence assertions in the intake pipeline.
CREATE INDEX idx_assertions_confidence ON assertions (confidence);
