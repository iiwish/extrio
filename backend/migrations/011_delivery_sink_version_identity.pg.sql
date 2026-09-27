UPDATE deliveries
SET sink_version_id = sink_id || '#legacy-' || id
WHERE sink_version_id IS NULL;

ALTER TABLE deliveries ALTER COLUMN sink_version_id SET NOT NULL;
ALTER TABLE deliveries DROP CONSTRAINT IF EXISTS deliveries_item_event_id_sink_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_deliveries_event_sink_version
ON deliveries(item_event_id, sink_version_id);
