CREATE TABLE auth_login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key TEXT NOT NULL,
    attempted_at TEXT NOT NULL
);

CREATE INDEX idx_auth_login_attempts_scope ON auth_login_attempts(scope_key, attempted_at);
