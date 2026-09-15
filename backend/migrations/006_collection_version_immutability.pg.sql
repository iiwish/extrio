CREATE OR REPLACE TRIGGER collection_versions_immutable_update
BEFORE UPDATE ON collection_versions FOR EACH ROW EXECUTE FUNCTION extrio_abort_immutable('collection_versions');
CREATE OR REPLACE TRIGGER collection_versions_immutable_delete
BEFORE DELETE ON collection_versions FOR EACH ROW EXECUTE FUNCTION extrio_abort_immutable('collection_versions');
