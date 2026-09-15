CREATE TABLE IF NOT EXISTS collection_versions (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    data TEXT NOT NULL,
    UNIQUE(collection_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_collection_versions_collection_id ON collection_versions(collection_id, version_number DESC);
