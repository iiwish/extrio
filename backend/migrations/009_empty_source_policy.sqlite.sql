CREATE TABLE deleted_collectors (id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL);

DROP TRIGGER collection_policies_immutable_delete;
CREATE TRIGGER collection_policies_immutable_delete
BEFORE DELETE ON collection_policies
WHEN OLD.version <> 1
 OR NOT EXISTS (SELECT 1 FROM collectors WHERE id=OLD.collector_id AND json_extract(data, '$.emptyDeleteAuthorized')=1)
 OR EXISTS (SELECT 1 FROM runs WHERE collector_id=OLD.collector_id)
 OR EXISTS (SELECT 1 FROM operations WHERE collector_id=OLD.collector_id)
 OR EXISTS (SELECT 1 FROM rule_versions WHERE collector_id=OLD.collector_id)
BEGIN SELECT RAISE(ABORT, 'collection_policies are immutable'); END;
