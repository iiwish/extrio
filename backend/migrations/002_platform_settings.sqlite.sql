-- v0.6 "Platform settings": UI-configurable collection policy flags.
--
-- Scalar platform settings managed from the Settings UI (设置 → 采集策略) live in
-- this dedicated table. The JSON-blob platform_settings table created by
-- 000_baseline (model provider configuration) keeps its own schema and is
-- intentionally untouched; scalar toggles with an audit trail get their own
-- (key, value, updated_by, updated_at) shape here.
--
-- Preserve the historical permissive candidate value for upgraded instances,
-- but the deployment configuration is now a safety ceiling: production
-- EXTRIO_ALLOW_HTTP_PUBLIC=false keeps anonymous HTTP disabled even when this
-- row is true. Local development explicitly enables the deployment exception.
-- INSERT OR IGNORE keeps re-runs from clobbering an administrator's choice.
CREATE TABLE IF NOT EXISTS platform_setting_values (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT NOT NULL
);
INSERT OR IGNORE INTO platform_setting_values(key, value, updated_by, updated_at)
VALUES ('allowAnonymousHttp', 'true', NULL, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
