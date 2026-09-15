"""Verified offline instance backups and empty-target restores."""

import argparse
import configparser
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict

from extrio.config import get_settings
from extrio.credentials import CredentialCipher
from extrio.instance_guard import instance_lock, restore_marker
from extrio.integrity import LocalEd25519Signer
from extrio.store import Store
from extrio.store_dialect import resolve_database

SNAPSHOT_NAME = "database.snapshot"
PG_DUMP_NAME = "database.pg_dump"
MANIFEST_NAME = "backup_manifest.json"
CHECKSUMS_NAME = "SHA256SUMS"
SIGNING_MEMBER = "keys/signing.pem"
CREDENTIAL_MEMBER = "keys/credential.key"


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
    return urlunsplit((parts.scheme, parts.netloc.split("@", 1)[-1], parts.path, "", ""))


def _effective_database_url(database_url: str | None) -> str | None:
    return database_url if database_url is not None else get_settings().database_url


def _archive_files(archive: Path) -> set[str]:
    names = set()
    if archive.is_symlink():
        raise RuntimeError("archive must not be a symlink")
    for path in archive.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("archive must not contain symlinks")
        if path.is_file():
            names.add(path.relative_to(archive).as_posix())
        elif not path.is_dir():
            raise RuntimeError("archive contains a non-regular member")
    return names


def _write_checksums(archive: Path, names: list[str]) -> None:
    (archive / CHECKSUMS_NAME).write_text("".join(f"{_sha256(archive / name)}  {name}\n" for name in sorted(names)), encoding="utf-8")


def _verify_checksums(archive: Path) -> None:
    names = _archive_files(archive)
    if CHECKSUMS_NAME not in names or MANIFEST_NAME not in names:
        raise RuntimeError("archive is missing its manifest or checksums")
    expected_files = {}
    for line in (archive / CHECKSUMS_NAME).read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise RuntimeError("invalid archive checksum entry")
        expected, name = parts
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name or name in expected_files or name == CHECKSUMS_NAME:
            raise RuntimeError("invalid archive checksum path")
        expected_files[name] = expected
    if set(expected_files) != names - {CHECKSUMS_NAME}:
        raise RuntimeError("archive checksum member list is incomplete")
    for name, expected in expected_files.items():
        if _sha256(archive / name) != expected:
            raise RuntimeError(f"checksum mismatch for {name}")


def _pg_tool(program: str, arguments: list[str], database_url: str) -> None:
    configuration = configparser.ConfigParser(interpolation=None)
    values = conninfo_to_dict(database_url)
    if any("\n" in value or "\r" in value for value in values.values()):
        raise RuntimeError("multiline PostgreSQL connection parameters are unsupported")
    configuration["extrio_maintenance"] = values
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="extrio-pg-service-") as service:
        configuration.write(service, space_around_delimiters=False)
        service.flush()
        environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        environment["PGSERVICEFILE"] = service.name
        result = subprocess.run(
            [program, *arguments, "--dbname=service=extrio_maintenance"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(f"{program} failed (exit {result.returncode}); check server access and client/server versions")


def _assert_empty_database(dialect, path: Path, url: str | None) -> None:
    if dialect.name == "sqlite":
        if any(
            path.with_name(path.name + suffix).exists() or path.with_name(path.name + suffix).is_symlink()
            for suffix in ("", "-wal", "-shm")
        ):
            raise RuntimeError("restore requires an empty target database path")
    else:
        with psycopg.connect(url) as connection:
            row = connection.execute(
                "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' LIMIT 1"
            ).fetchone()
        if row:
            raise RuntimeError("restore requires an empty target PostgreSQL database")


def _assert_stopped(store: Store) -> None:
    with store.connect() as connection:
        if store.dialect.name == "sqlite":
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_instances'").fetchone()
        else:
            exists = connection.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='worker_instances'"
            ).fetchone()
        if exists:
            cutoff = (datetime.now(UTC) - timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
            if connection.execute("SELECT 1 FROM worker_instances WHERE status='running' AND last_seen>=? LIMIT 1", (cutoff,)).fetchone():
                raise RuntimeError("worker is still running; stop all instance writers before offline maintenance")


def _copy_file(source: Path, target: Path, *, on_created=None) -> None:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    if on_created:
        on_created(target)
    with os.fdopen(descriptor, "wb") as destination, source.open("rb") as origin:
        shutil.copyfileobj(origin, destination)
        destination.flush()
        os.fsync(destination.fileno())


def _copy_regular_tree(source: Path, target: Path, *, on_created=None) -> None:
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError("artifact source must be a directory without symlinks")
    target.mkdir(parents=True, exist_ok=False)
    if on_created:
        on_created(target)
    for path in source.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("artifact symlinks are not supported in backups")
        destination = target / path.relative_to(source)
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_file(path, destination)
        else:
            raise RuntimeError("artifact source contains a non-regular file")


def _validate_keys(settings, store: Store) -> None:
    for path in (settings.signing_private_key_path, settings.credential_encryption_key_path):
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError("full backup requires existing permission-restricted signing and credential keys")
    cipher = CredentialCipher(settings.credential_encryption_key_path)
    cipher._keys()
    signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
    trust = store.get_signing_key(settings.signing_key_id)
    if trust and trust["publicKeyPem"] != signer.public_key_pem():
        raise RuntimeError("configured signing key does not match the database trust identity")
    credentials = (store.get_platform_setting("model-provider-credentials") or {}).get("credentials", {})
    with store.connect() as connection:
        tokens = [
            row["secret_encrypted"]
            for row in connection.execute("SELECT secret_encrypted FROM sinks WHERE secret_encrypted IS NOT NULL").fetchall()
        ]
    if any(not cipher.can_decrypt(token) for token in [*credentials.values(), *tokens]):
        raise RuntimeError("credential keyring cannot decrypt all stored credentials")


def create_backup(
    output_path: Path, *, database_url: str | None = None, database_path: Path | None = None, full: bool = False, offline: bool = False
) -> Path:
    settings = get_settings()
    effective_url = _effective_database_url(database_url)
    dialect, sqlite_path = resolve_database(effective_url, database_path or settings.database_path)
    archive = output_path.absolute()
    if archive.is_symlink() or (archive.exists() and (not archive.is_dir() or any(archive.iterdir()))):
        raise RuntimeError("backup output directory must be empty")
    if full and not offline:
        raise RuntimeError("full backup requires --offline and stopped API/Worker processes")
    if dialect.name == "sqlite" and not sqlite_path.is_file():
        raise RuntimeError("source database does not exist")
    if full and archive.resolve().is_relative_to(settings.artifact_path.resolve()):
        raise RuntimeError("backup output must be outside the artifact directory")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with instance_lock(settings.artifact_path, exclusive=True) if full else nullcontext():
        store = Store(sqlite_path, database_url=effective_url or "")
        if full:
            _assert_stopped(store)
            _validate_keys(settings, store)
        with tempfile.TemporaryDirectory(prefix=".extrio-backup-", dir=archive.parent) as temporary:
            staged = Path(temporary) / "archive"
            staged.mkdir(mode=0o700)
            database_file = SNAPSHOT_NAME if dialect.name == "sqlite" else PG_DUMP_NAME
            if dialect.name == "sqlite":
                with sqlite3.connect(sqlite_path, isolation_level=None) as connection:
                    connection.execute("VACUUM INTO ?", (str(staged / database_file),))
                source = {"kind": "path", "value": str(sqlite_path)}
            else:
                _pg_tool("pg_dump", ["--format=custom", f"--file={staged / database_file}"], effective_url)
                source = {"kind": "url", "value": _redact_url(effective_url)}
            manifest = {
                "formatVersion": 2,
                "scope": "full" if full else "database_only",
                "dialect": dialect.name,
                "createdAt": _utc_now(),
                "database": source,
                "artifactPath": str(settings.artifact_path),
            }
            if full:
                _copy_regular_tree(settings.artifact_path, staged / "artifacts")
                (staged / "keys").mkdir(mode=0o700)
                _copy_file(settings.signing_private_key_path, staged / SIGNING_MEMBER)
                _copy_file(settings.credential_encryption_key_path, staged / CREDENTIAL_MEMBER)
                manifest.update(signingKeyId=settings.signing_key_id, tenantId=settings.tenant_id, consistency="offline-instance-lock")
            (staged / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            names = _archive_files(staged)
            _write_checksums(staged, list(names))
            for name in _archive_files(staged):
                (staged / name).chmod(0o600)
            if archive.exists():
                archive.rmdir()
            os.rename(staged, archive)
    print(f"backup complete: scope={manifest['scope']} dialect={dialect.name} archive={archive}")
    return archive


def restore_backup(
    archive: Path, *, database_url: str | None = None, database_path: Path | None = None, offline: bool = False, database_only: bool = True
) -> Path:
    settings = get_settings()
    effective_url = _effective_database_url(database_url)
    dialect, sqlite_path = resolve_database(effective_url, database_path or settings.database_path)
    _verify_checksums(archive)
    manifest = json.loads((archive / MANIFEST_NAME).read_text(encoding="utf-8"))
    if manifest.get("dialect") != dialect.name:
        raise RuntimeError("archive dialect does not match configured target")
    full = manifest.get("scope") == "full"
    if full and not offline:
        raise RuntimeError("full restore requires --offline")
    if not full and not database_only:
        raise RuntimeError("database-only archive is not a full recovery set; explicitly select --database-only")
    snapshot = archive / (SNAPSHOT_NAME if dialect.name == "sqlite" else PG_DUMP_NAME)
    if not snapshot.is_file():
        raise RuntimeError("archive is missing its database snapshot")
    if dialect.name == "sqlite" and sqlite_path.resolve().is_relative_to(archive.resolve()):
        raise RuntimeError("restore target must be outside the archive")
    targets = []
    if full:
        if manifest.get("signingKeyId") != settings.signing_key_id or manifest.get("tenantId") != settings.tenant_id:
            raise RuntimeError("configure the target tenant and signing key ID to match the archive")
        if not (archive / SIGNING_MEMBER).is_file() or not (archive / CREDENTIAL_MEMBER).is_file() or not (archive / "artifacts").is_dir():
            raise RuntimeError("full archive is missing artifacts or keys")
        targets = [
            (archive / "artifacts", settings.artifact_path),
            (archive / SIGNING_MEMBER, settings.signing_private_key_path),
            (archive / CREDENTIAL_MEMBER, settings.credential_encryption_key_path),
        ]
        destinations = [target.resolve() for _source, target in targets] + ([sqlite_path.resolve()] if dialect.name == "sqlite" else [])
        if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(destinations) for b in destinations[i + 1 :]):
            raise RuntimeError("restore destinations must not overlap")
        if any(destination.is_relative_to(archive.resolve()) for destination in destinations):
            raise RuntimeError("restore target must be outside the archive")
        if any(target.exists() or target.is_symlink() for _source, target in targets):
            raise RuntimeError("full restore requires empty artifact and key targets")
    with instance_lock(settings.artifact_path, exclusive=True) if full else nullcontext():
        _assert_empty_database(dialect, sqlite_path, effective_url)
        installed = []
        marker = restore_marker(settings.artifact_path)
        if full:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                json.dump({"archive": str(archive.absolute()), "startedAt": _utc_now()}, file)
        try:
            for source, target in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    _copy_regular_tree(source, target, on_created=installed.append)
                else:
                    _copy_file(source, target, on_created=installed.append)
            if dialect.name == "sqlite":
                with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as connection:
                    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("database snapshot failed SQLite integrity check")
                sqlite_path.parent.mkdir(parents=True, exist_ok=True)
                _copy_file(snapshot, sqlite_path, on_created=installed.append)
            else:
                _pg_tool("pg_restore", ["--single-transaction", "--exit-on-error", "--no-owner", str(snapshot)], effective_url)
        except BaseException:
            for path in reversed(installed):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            if full:
                marker.unlink(missing_ok=True)
            raise
        if full:
            marker.unlink()
    print("restore complete: start the matching API and Worker, then verify /readyz and stored evidence")
    return sqlite_path if dialect.name == "sqlite" else archive


def run_backup() -> None:
    parser = argparse.ArgumentParser(prog="extrio-backup", description="Create a full offline Extrio instance backup")
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--offline", action="store_true", help="confirm API and Worker are stopped")
    parser.add_argument("--database-only", action="store_true", help="database snapshot only, not disaster recovery")
    args = parser.parse_args()
    try:
        create_backup(args.output_path, full=not args.database_only, offline=args.offline)
    except Exception as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


def run_restore() -> None:
    parser = argparse.ArgumentParser(prog="extrio-restore", description="Restore into an empty Extrio instance")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--database-only", action="store_true")
    args = parser.parse_args()
    try:
        restore_backup(args.archive, offline=args.offline, database_only=args.database_only)
    except Exception as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
