-- v0.6 "Platform settings": UI-configurable collection policy flags.
--
-- Scalar platform settings managed from the Settings UI (设置 → 采集策略) live in
-- this dedicated table. The JSON-blob platform_settings table created by
-- 000_baseline (model provider configuration) keeps its own schema and is
-- intentionally untouched; scalar toggles with an audit trail get their own
-- (key, value, updated_by, updated_at) shape here. TEXT columns on both
-- dialects (no jsonb needed).
--
-- Preserve the historical permissive candidate value for upgraded instances,
-- but the deployment configuration is now a safety ceiling: production
-- EXTRIO_ALLOW_HTTP_PUBLIC=false keeps anonymous HTTP disabled even when this
-- row is true. Local development explicitly enables the deployment exception.
-- ON CONFLICT DO NOTHING keeps re-runs from clobbering an administrator's choice.
CREATE TABLE IF NOT EXISTS platform_setting_values (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT NOT NULL
);
INSERT INTO platform_setting_values(key, value, updated_by, updated_at)
VALUES ('allowAnonymousHttp', 'true', NULL, to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (key) DO NOTHING;
