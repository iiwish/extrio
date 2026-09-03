-- v0.4 "Team-ready": user account enablement flag.
-- Existing accounts stay active; the explicit UPDATE is a defensive backfill
-- alongside the NOT NULL DEFAULT for upgrades from v0.3.
ALTER TABLE auth_users ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT TRUE;
UPDATE auth_users SET enabled = TRUE;
