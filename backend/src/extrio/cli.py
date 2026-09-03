"""Backup and restore entry points for the Extrio store.

``extrio-backup <output-path>`` writes a self-verifying archive directory
holding a consistent database snapshot (``VACUUM INTO`` for SQLite,
``pg_dump -Fc`` for PostgreSQL), a manifest with the artifact path reference,
and a SHA256SUMS checksum file. ``extrio-restore <archive>`` verifies the
checksums, replaces the configured database with the snapshot, and prints the
next-step hint. Restoring the database does not restore artifacts or keys;
those directories must be restored separately from the referenced paths.
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from extrio.config import get_settings
from extrio.store_dialect import resolve_database

SNAPSHOT_NAME = "database.snapshot"
PG_DUMP_NAME = "database.pg_dump"
MANIFEST_NAME = "backup_manifest.json"
CHECKSUMS_NAME = "SHA256SUMS"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.split("@", 1)[-1]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _effective_database_url(database_url: str | None) -> str | None:
    return database_url if database_url is not None else get_settings().database_url


def _write_checksums(archive: Path, names: list[str]) -> None:
    lines = [f"{_sha256(archive / name)}  {name}\n" for name in names]
    (archive / CHECKSUMS_NAME).write_text("".join(lines), encoding="utf-8")


def _verify_checksums(archive: Path) -> None:
    for line in (archive / CHECKSUMS_NAME).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, name = line.split("  ", 1)
        actual = _sha256(archive / name)
        if actual != expected:
            raise RuntimeError(f"checksum mismatch for {name}: expected {expected}, got {actual}")


def create_backup(
    output_path: Path,
    *,
    database_url: str | None = None,
    database_path: Path | None = None,
) -> Path:
    """Create a backup archive directory at ``output_path`` and return it."""

    settings = get_settings()
    effective_url = _effective_database_url(database_url)
    dialect, sqlite_path = resolve_database(effective_url, database_path or settings.database_path)
    archive = output_path
    if archive.exists() and any(archive.iterdir()):
        raise RuntimeError(f"backup output directory is not empty: {archive}")
    archive.mkdir(parents=True, exist_ok=True)

    if dialect.name == "sqlite":
        snapshot = archive / SNAPSHOT_NAME
        connection = sqlite3.connect(sqlite_path, isolation_level=None)
        try:
            connection.execute("VACUUM INTO ?", (str(snapshot),))
        finally:
            connection.close()
        database_file = snapshot
        manifest_database = {"kind": "path", "value": str(sqlite_path)}
    else:
        if not isinstance(effective_url, str):
            raise RuntimeError("PostgreSQL backup requires a configured EXTRIO_DATABASE_URL")
        database_file = archive / PG_DUMP_NAME
        subprocess.run(
            ["pg_dump", "--format=custom", f"--file={database_file}", effective_url],
            check=True,
        )
        manifest_database = {"kind": "url", "value": _redact_url(effective_url)}

    manifest = {
        "dialect": dialect.name,
        "createdAt": _utc_now(),
        "database": manifest_database,
        "artifactPath": str(settings.artifact_path),
    }
    (archive / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_checksums(archive, [MANIFEST_NAME, database_file.name])
    print(f"backup complete: dialect={dialect.name} database={database_file.name} archive={archive}")
    return archive


def restore_backup(
    archive: Path,
    *,
    database_url: str | None = None,
    database_path: Path | None = None,
) -> Path:
    """Verify ``archive`` and replace the configured database with its snapshot."""

    settings = get_settings()
    effective_url = _effective_database_url(database_url)
    dialect, sqlite_path = resolve_database(effective_url, database_path or settings.database_path)
    manifest_path = archive / MANIFEST_NAME
    if not manifest_path.is_file() or not (archive / CHECKSUMS_NAME).is_file():
        raise RuntimeError(f"archive is missing its manifest or checksums: {archive}")
    _verify_checksums(archive)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dialect") != dialect.name:
        raise RuntimeError(f"archive dialect {manifest.get('dialect')!r} does not match configured dialect {dialect.name!r}")

    snapshot = archive / (SNAPSHOT_NAME if dialect.name == "sqlite" else PG_DUMP_NAME)
    if not snapshot.is_file():
        raise RuntimeError(f"archive is missing its database snapshot: {snapshot}")

    if dialect.name == "sqlite":
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        staged = sqlite_path.with_name(f"{sqlite_path.name}.restore-tmp")
        shutil.copyfile(snapshot, staged)
        os.replace(staged, sqlite_path)
        for suffix in ("-wal", "-shm"):
            sidecar = sqlite_path.with_name(f"{sqlite_path.name}{suffix}")
            sidecar.unlink(missing_ok=True)
    else:
        if not isinstance(effective_url, str):
            raise RuntimeError("PostgreSQL restore requires a configured EXTRIO_DATABASE_URL")
        subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", f"--dbname={effective_url}", str(snapshot)],
            check=True,
        )
    print("restore complete. Restart extrio-api and extrio-worker (or `docker compose restart`) to pick up the restored state.")
    return sqlite_path if dialect.name == "sqlite" else archive


def run_backup() -> None:
    parser = argparse.ArgumentParser(prog="extrio-backup", description="Create an Extrio database backup archive")
    parser.add_argument("output_path", type=Path, help="directory to write the backup archive into")
    args = parser.parse_args()
    try:
        create_backup(args.output_path)
    except Exception as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def run_restore() -> None:
    parser = argparse.ArgumentParser(prog="extrio-restore", description="Restore an Extrio database from a backup archive")
    parser.add_argument("archive", type=Path, help="backup archive directory created by extrio-backup")
    args = parser.parse_args()
    try:
        restore_backup(args.archive)
    except Exception as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
