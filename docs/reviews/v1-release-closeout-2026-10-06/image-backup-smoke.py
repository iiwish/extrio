"""Verify both offline recovery paths in the non-root candidate container."""

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import extrio.cli as cli
import psycopg
from extrio.config import Settings
from extrio.credentials import CredentialCipher
from extrio.integrity import LocalEd25519Signer
from extrio.store import Store
from psycopg import sql


def roundtrip(root, source_url="", target_url=""):
    settings = Settings(
        database_url=source_url, database_path=root / "source/database.db", artifact_path=root / "source/artifacts",
        signing_private_key_path=root / "source/keys/signing.pem",
        credential_encryption_key_path=root / "source/keys/credential.key",
        contracts_path=Path("/app/docs/contracts"), seed_demo=False,
    )
    store = Store(settings.database_path, database_url=source_url)
    store.initialize(migrate=True)
    collector = store.create_collector("Image recovery fixture", "Recovery", "https://example.test/notice", "example.test")
    cipher = CredentialCipher(settings.credential_encryption_key_path)
    store.create_sink(collector["id"], url="https://hooks.example.test/", secret="synthetic-image-fixture", cipher=cipher)
    signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
    store.ensure_signing_key(signer.trust_record(tenant_id=settings.tenant_id, revision=1))
    settings.artifact_path.mkdir(parents=True)
    (settings.artifact_path / "sample.html").write_text("<h1>Synthetic immutable source</h1>")
    cli.get_settings = lambda: settings
    archive = cli.create_backup(root / "archive", full=True, offline=True)
    target = settings.model_copy(update={
        "database_url": target_url, "database_path": root / "target/database.db", "artifact_path": root / "target/artifacts",
        "signing_private_key_path": root / "target/keys/signing.pem",
        "credential_encryption_key_path": root / "target/keys/credential.key",
    })
    cli.get_settings = lambda: target
    cli.restore_backup(archive, offline=True)
    restored = Store(target.database_path, database_url=target_url)
    assert restored.get_collector(collector["id"]) == store.get_collector(collector["id"])
    sink = restored.list_sinks_for_collector(collector["id"])[0]
    recovered_sink = restored.get_sink(sink["id"], cipher=CredentialCipher(target.credential_encryption_key_path))
    assert recovered_sink["secret"] == "synthetic-image-fixture"
    assert target.signing_private_key_path.read_bytes() == settings.signing_private_key_path.read_bytes()
    assert (target.artifact_path / "sample.html").read_bytes() == (settings.artifact_path / "sample.html").read_bytes()


def main():
    assert os.getuid() == 10001
    assert all(shutil.which(tool) is None for tool in ("curl", "Xvfb", "Xorg"))
    admin_url = os.environ["EXTRIO_TEST_DATABASE_URL"]
    target = urlsplit(admin_url)
    assert target.hostname == "host.docker.internal" and target.port == 55438 and target.path == "/postgres"
    names = ["extrio_image_recovery_" + uuid.uuid4().hex[:12] for _ in range(2)]
    urls = [admin_url.rsplit("/", 1)[0] + "/" + name for name in names]
    original_run = cli.subprocess.run

    def diagnostic_run(*args, **kwargs):
        result = original_run(*args, **kwargs)
        if result.returncode:
            print(result.stderr)
        return result

    cli.subprocess.run = diagnostic_run
    with tempfile.TemporaryDirectory(prefix="extrio-image-recovery-") as temp:
        root = Path(temp)
        roundtrip(root / "sqlite")
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                for name in names:
                    connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            roundtrip(root / "postgres", *urls)
        finally:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                for name in names:
                    connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    print(json.dumps({"uid": os.getuid(), "sqliteVersion": sqlite3.sqlite_version, "sqliteFullRecovery": "passed",
                      "postgresFullRecovery": "passed", "keysAndCredentials": "verified", "setupToolsRemoved": True}))


if __name__ == "__main__":
    main()
