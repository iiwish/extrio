PRAGMA legacy_alter_table=ON;

ALTER TABLE deliveries RENAME TO deliveries_legacy;

CREATE TABLE deliveries (
    id TEXT PRIMARY KEY,
    collector_id TEXT NOT NULL,
    sink_id TEXT NOT NULL,
    sink_version_id TEXT NOT NULL,
    item_event_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivering', 'delivered', 'failed', 'dead_lettered')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    lease_until TEXT,
    last_status_code INTEGER,
    last_error TEXT,
    redelivery_count INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    cycle_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (item_event_id, sink_version_id),
    FOREIGN KEY (collector_id) REFERENCES collectors(id),
    FOREIGN KEY (sink_id) REFERENCES sinks(id) ON DELETE CASCADE
);

INSERT INTO deliveries (
    id, collector_id, sink_id, sink_version_id, item_event_id, status, attempt_count,
    next_attempt_at, lease_until, last_status_code, last_error, redelivery_count,
    lease_token, cycle_attempts, created_at, updated_at
)
SELECT
    id, collector_id, sink_id, COALESCE(sink_version_id, sink_id || '#legacy-' || id),
    item_event_id, status, attempt_count, next_attempt_at, lease_until, last_status_code,
    last_error, redelivery_count, lease_token, cycle_attempts, created_at, updated_at
FROM deliveries_legacy;

DROP TABLE deliveries_legacy;

PRAGMA legacy_alter_table=OFF;
