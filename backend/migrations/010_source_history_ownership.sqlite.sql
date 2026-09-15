CREATE TABLE source_history_ownership (
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    collector_id TEXT NOT NULL REFERENCES collectors(id),
    collection_id TEXT NOT NULL REFERENCES collections(id),
    data TEXT NOT NULL,
    PRIMARY KEY(resource_type, resource_id)
);
CREATE INDEX idx_source_history_owner ON source_history_ownership(collector_id, collection_id);
CREATE TRIGGER source_history_ownership_immutable_update
BEFORE UPDATE ON source_history_ownership BEGIN SELECT RAISE(ABORT, 'source_history_ownership are immutable'); END;
CREATE TRIGGER source_history_ownership_immutable_delete
BEFORE DELETE ON source_history_ownership BEGIN SELECT RAISE(ABORT, 'source_history_ownership are immutable'); END;
