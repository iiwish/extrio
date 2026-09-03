-- v0.6 "Platform settings": UI-configurable collection policy flags.
--
-- Scalar platform settings managed from the Settings UI (设置 → 采集策略) live in
-- this dedicated table. The JSON-blob platform_settings table created by
-- 000_baseline (model provider configuration) keeps its own schema and is
-- intentionally untouched; scalar toggles with an audit trail get their own
-- (key, value, updated_by, updated_at) shape here. TEXT columns on both
-- dialects (no jsonb needed).
--
-- Seed allowAnonymousHttp='true' matches the v0.6 default: anonymous HTTP
-- sources are allowed unless an administrator disables the flag. Deployments
-- upgrading from v0.5 keep their current behavior: the deprecated
-- EXTRIO_ALLOW_HTTP_PUBLIC env var no longer acts as a runtime override — it
-- only supplies the config fallback used while this row is absent — and the
-- seeded 'true' preserves the risk-accepting posture such deployments had
-- already opted into via the env var. ON CONFLICT DO NOTHING keeps re-runs
-- from clobbering a value an administrator has since changed in the UI.
CREATE TABLE IF NOT EXISTS platform_setting_values (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT NOT NULL
);
INSERT INTO platform_setting_values(key, value, updated_by, updated_at)
VALUES ('allowAnonymousHttp', 'true', NULL, to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
ON CONFLICT (key) DO NOTHING;
