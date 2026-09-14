CREATE TRIGGER IF NOT EXISTS collection_versions_immutable_update
BEFORE UPDATE ON collection_versions BEGIN SELECT RAISE(ABORT, 'collection_versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS collection_versions_immutable_delete
BEFORE DELETE ON collection_versions BEGIN SELECT RAISE(ABORT, 'collection_versions are immutable'); END;
