CREATE TABLE data_migrations (
    id TEXT PRIMARY KEY,
    completed_at TEXT NOT NULL
);
CREATE INDEX idx_schedule_occurrences_pending ON schedule_occurrences(status, updated_at, occurrence_key);
