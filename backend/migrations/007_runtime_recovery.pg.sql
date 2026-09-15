ALTER TABLE deliveries ADD COLUMN lease_token TEXT;
ALTER TABLE deliveries ADD COLUMN cycle_attempts INTEGER NOT NULL DEFAULT 0;
CREATE TABLE worker_instances (
    id TEXT PRIMARY KEY,
    deployment_digest TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL
);
