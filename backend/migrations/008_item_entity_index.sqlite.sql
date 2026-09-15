CREATE INDEX IF NOT EXISTS idx_items_entity_latest ON items(
    json_extract(data, '$.collectorId'),
    json_extract(data, '$.entityKey'),
    json_extract(data, '$.observedAt') DESC,
    id DESC
);
