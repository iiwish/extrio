CREATE TABLE collection_migrations (
    collector_id TEXT PRIMARY KEY REFERENCES collectors(id),
    data JSONB NOT NULL
);

CREATE TABLE field_suggestions (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id),
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    created_at TEXT NOT NULL,
    data JSONB NOT NULL
);
CREATE INDEX idx_field_suggestions_queue ON field_suggestions(status, created_at);
CREATE INDEX idx_field_suggestions_collection ON field_suggestions(collection_id, created_at);
