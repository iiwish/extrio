"""Read-only deployment diagnostics, with no secret values or filesystem paths."""

import json
import os
import shutil

from extrio.config import get_settings
from extrio.instance_guard import restore_marker
from extrio.runtime_health import deployment_digest, runtime_status
from extrio.store import Store


def diagnose(settings):
    store = Store(settings.database_path, database_url=settings.database_url or "")
    report = {"ready": False, "reason": "database_unavailable", "database": store.dialect.name}
    if store.dialect.name == "sqlite" and not store.path.is_file():
        return report
    try:
        with store.connect() as connection:
            applied = {row["id"] for row in connection.execute("SELECT id FROM schema_migrations").fetchall()}
        suffix = ".sqlite.sql" if store.dialect.name == "sqlite" else ".pg.sql"
        expected = {path.name.removesuffix(suffix) for path in store._migration_dir().glob(f"*{suffix}")}
        report["pendingMigrations"] = sorted(expected - applied)
        if expected - applied:
            return {**report, "reason": "migrations_pending"}
        report.update(runtime_status(store, deployment_digest(settings), settings))
    except Exception:
        return {**report, "ready": False, "reason": "database_unavailable"}
    path = settings.artifact_path
    report["artifactWritable"] = path.is_dir() and not path.is_symlink() and os.access(path, os.R_OK | os.W_OK | os.X_OK)
    report["artifactFreeBytes"] = shutil.disk_usage(path).free if path.is_dir() else None
    report["backupToolsAvailable"] = store.dialect.name == "sqlite" or all(shutil.which(name) for name in ("pg_dump", "pg_restore"))
    if restore_marker(path).exists():
        report.update(ready=False, reason="restore_incomplete")
    elif not report["artifactWritable"]:
        report.update(ready=False, reason="artifact_unavailable")
    elif not report["backupToolsAvailable"]:
        report.update(ready=False, reason="backup_tools_unavailable")
    return report


def run_doctor():
    report = diagnose(get_settings())
    print(json.dumps(report))
    raise SystemExit(0 if report["ready"] else 1)
