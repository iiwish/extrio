CREATE TABLE deleted_collectors (id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL);

CREATE FUNCTION extrio_guard_policy_delete() RETURNS trigger AS $$
BEGIN
    IF OLD.version <> 1
       OR NOT EXISTS (SELECT 1 FROM collectors WHERE id=OLD.collector_id AND data->>'emptyDeleteAuthorized'='true')
       OR EXISTS (SELECT 1 FROM runs WHERE collector_id=OLD.collector_id)
       OR EXISTS (SELECT 1 FROM operations WHERE collector_id=OLD.collector_id)
       OR EXISTS (SELECT 1 FROM rule_versions WHERE collector_id=OLD.collector_id) THEN
        RAISE EXCEPTION 'collection_policies are immutable';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER collection_policies_immutable_delete ON collection_policies;
CREATE TRIGGER collection_policies_immutable_delete
BEFORE DELETE ON collection_policies FOR EACH ROW EXECUTE FUNCTION extrio_guard_policy_delete();
