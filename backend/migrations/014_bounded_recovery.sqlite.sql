CREATE TABLE recovery_batches (
    id TEXT PRIMARY KEY,
    seed_run_id TEXT NOT NULL UNIQUE,
    collector_id TEXT NOT NULL,
    status TEXT NOT NULL,
    hold_until TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX recovery_batches_status ON recovery_batches(status);
CREATE INDEX recovery_batches_hold ON recovery_batches(hold_until);
