CREATE INDEX IF NOT EXISTS idx_items_entity_latest ON items(
    (data->>'collectorId'),
    (data->>'entityKey'),
    (data->>'observedAt') DESC,
    id DESC
);
