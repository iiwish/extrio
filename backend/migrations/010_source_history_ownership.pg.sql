CREATE TABLE source_history_ownership (
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    collector_id TEXT NOT NULL REFERENCES collectors(id),
    collection_id TEXT NOT NULL REFERENCES collections(id),
    data JSONB NOT NULL,
    PRIMARY KEY(resource_type, resource_id)
);
CREATE INDEX idx_source_history_owner ON source_history_ownership(collector_id, collection_id);
CREATE TRIGGER source_history_ownership_immutable_update
BEFORE UPDATE ON source_history_ownership FOR EACH ROW EXECUTE FUNCTION extrio_abort_immutable('source_history_ownership');
CREATE TRIGGER source_history_ownership_immutable_delete
BEFORE DELETE ON source_history_ownership FOR EACH ROW EXECUTE FUNCTION extrio_abort_immutable('source_history_ownership');
