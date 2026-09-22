-- Web intake queue: one row per submitted URL.
-- `status` is pending -> running -> done|failed, no retry path — a failed row
-- stays failed; resubmitting the URL is a new row.
CREATE TABLE intake_queue (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_intake_queue_status ON intake_queue (status);
