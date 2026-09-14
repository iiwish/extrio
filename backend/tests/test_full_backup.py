import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from test_store_pg import pg_store as pg_store

from extrio.cli import create_backup, restore_backup
from extrio.config import Settings
from extrio.credentials import CredentialCipher
from extrio.integrity import LocalEd25519Signer
from extrio.store import Store


def add_history(settings, store, collector):
    from test_worker import accepted_item

    from extrio.contracts import ContractBundle
    from extrio.harvest import build_gather_spec
    from extrio.integrity import build_rule_attestation, immutable_rule_version
    from extrio.local_evidence import LocalEvidence
    from extrio.maintenance import rotate_credentials

    contracts = ContractBundle(settings.contracts_path)
    signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
    for number in (1, 2):
        spec = build_gather_spec(collector, contracts)
        rule = immutable_rule_version(collector_id=collector["id"], spec=spec, rule_version_id=f"rule_backup_{number}")
        attestation = build_rule_attestation(
            spec=rule["gatherSpec"], rule_version_id=rule["id"], review_decisions={"title": "approved"}, signer=signer, contracts=contracts
        )
        store.publish_rule_bundle(
            collector_id=collector["id"],
            rule_version=rule,
            attestation=attestation,
            collector_changes={"activeRuleVersion": rule["id"], "status": "published"},
            audit={"actorId": "user_backup", "action": "rule.published", "requestId": f"backup_rule_{number}"},
        )
    collection = store.get_collection(collector["collectionId"])
    changed = store.change_collection(
        collection["id"],
        collection["revision"],
        {
            "fieldDraft": {
                "fields": [
                    {
                        "key": "title",
                        "label": "Title",
                        "description": "",
                        "type": "string",
                        "required": True,
                        "identity": True,
                        "fingerprint": True,
                    }
                ]
            }
        },
    )
    store.publish_collection_version(collection["id"], changed["revision"], "user_backup")
    evidence = LocalEvidence(settings.artifact_path, "run_backup", 30)
    evidence.write("detail-001.html", "<h1>Historical evidence</h1>")
    store.save_run(
        {
            "id": "run_backup",
            "collectorId": collector["id"],
            "status": "succeeded",
            "localEvidenceDigest": evidence.finish(complete=True),
            "localEvidenceRef": "attempt_1",
        }
    )
    item = accepted_item(run_id="run_backup")
    item["collectorId"] = collector["id"]
    store.save_items("run_backup", [item])
    rotate_credentials(settings, store, offline=True)


def assert_history(settings, restored, original, collector):
    from extrio.integrity import verify_attestation_signature
    from extrio.local_evidence import evidence_status

    for number in (1, 2):
        assert restored.get_rule_version(f"rule_backup_{number}") == original.get_rule_version(f"rule_backup_{number}")
    with restored.connect() as connection:
        for row in connection.execute("SELECT data FROM rule_attestations").fetchall():
            attestation = restored.dialect.decode_json(row["data"])
            verify_attestation_signature(attestation, restored.get_signing_key(attestation["keyId"])["publicKeyPem"])
    assert restored.list_collection_versions(collector["collectionId"]) == original.list_collection_versions(collector["collectionId"])
    assert restored.list_items() == original.list_items()
    assert evidence_status(settings.artifact_path, restored.get_run("run_backup"))["state"] == "available"
    assert restored.verify_audit_chain(settings.tenant_id)


def setup_instance(root, monkeypatch, database_url=""):
    settings = Settings(
        database_url=database_url,
        database_path=root / "database.db",
        artifact_path=root / "artifacts",
        signing_private_key_path=root / "keys" / "signing.pem",
        credential_encryption_key_path=root / "keys" / "credential.key",
        contracts_path=Path(__file__).resolve().parents[2] / "docs" / "contracts",
        seed_demo=False,
    )
    monkeypatch.setattr("extrio.cli.get_settings", lambda: settings)
    store = Store(settings.database_path, database_url=database_url)
    store.initialize()
    collector = store.create_collector("Backup fixture", "Restore", "https://example.test/", "example.test")
    cipher = CredentialCipher(settings.credential_encryption_key_path)
    store.create_sink(collector["id"], url="https://hooks.example.test/", secret="fixture-secret", cipher=cipher)
    signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
    store.ensure_signing_key(signer.trust_record(tenant_id=settings.tenant_id, revision=1))
    settings.artifact_path.mkdir()
    (settings.artifact_path / "sample.html").write_text("<h1>Immutable source</h1>")
    return settings, store, collector


def test_full_backup_restores_database_artifacts_and_keys_into_empty_instance(tmp_path, monkeypatch):
    source, store, collector = setup_instance(tmp_path / "source", monkeypatch)
    add_history(source, store, collector)
    archive = create_backup(tmp_path / "archive", full=True, offline=True)
    manifest = json.loads((archive / "backup_manifest.json").read_text())
    assert manifest["scope"] == "full"
    assert "fixture-secret" not in (archive / "backup_manifest.json").read_text()
    target = source.model_copy(
        update={
            "database_path": tmp_path / "target" / "database.db",
            "artifact_path": tmp_path / "target" / "artifacts",
            "signing_private_key_path": tmp_path / "target" / "keys" / "signing.pem",
            "credential_encryption_key_path": tmp_path / "target" / "keys" / "credential.key",
        }
    )
    monkeypatch.setattr("extrio.cli.get_settings", lambda: target)
    restore_backup(archive, offline=True)
    restored = Store(target.database_path, database_url="")
    sink = restored.list_sinks_for_collector(collector["id"])[0]
    assert restored.get_sink(sink["id"], cipher=CredentialCipher(target.credential_encryption_key_path))["secret"] == "fixture-secret"
    assert target.signing_private_key_path.read_bytes() == source.signing_private_key_path.read_bytes()
    assert (target.artifact_path / "sample.html").read_bytes() == (source.artifact_path / "sample.html").read_bytes()
    assert restored.get_collector(collector["id"]) == store.get_collector(collector["id"])
    assert_history(target, restored, store, collector)


def test_full_backup_requires_quiescence_and_rejects_active_process(tmp_path, monkeypatch):
    settings, _store, _collector = setup_instance(tmp_path / "source", monkeypatch)
    with pytest.raises(RuntimeError, match="offline"):
        create_backup(tmp_path / "archive", full=True)
    from extrio.instance_guard import instance_lock

    with instance_lock(settings.artifact_path, exclusive=False):
        with pytest.raises(RuntimeError, match="running"):
            create_backup(tmp_path / "archive", full=True, offline=True)


def test_database_restore_never_overwrites_existing_instance(tmp_path, monkeypatch):
    settings, store, collector = setup_instance(tmp_path / "source", monkeypatch)
    archive = create_backup(tmp_path / "archive")
    with pytest.raises(RuntimeError, match="empty"):
        restore_backup(archive, database_path=settings.database_path)
    assert store.get_collector(collector["id"]) is not None


def test_archive_checksums_reject_path_traversal_and_missing_entries(tmp_path, monkeypatch):
    setup_instance(tmp_path / "source", monkeypatch)
    archive = create_backup(tmp_path / "archive")
    outside = tmp_path / "outside"
    outside.write_text("outside archive")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    (archive / "SHA256SUMS").write_text(f"{digest}  ../outside\n")
    with pytest.raises(RuntimeError, match="checksum|archive"):
        restore_backup(archive, database_path=tmp_path / "target.db")
    assert not (tmp_path / "target.db").exists()


def test_full_backup_does_not_follow_artifact_symlinks(tmp_path, monkeypatch):
    settings, _store, _collector = setup_instance(tmp_path / "source", monkeypatch)
    (settings.artifact_path / "leak").symlink_to(settings.credential_encryption_key_path)
    with pytest.raises(RuntimeError, match="symlink"):
        create_backup(tmp_path / "archive", full=True, offline=True)


def test_full_postgresql_restore_preserves_credentials_and_artifacts(pg_store, tmp_path, monkeypatch):
    source, _store, collector = setup_instance(tmp_path / "source", monkeypatch, pg_store.database_url)
    add_history(source, _store, collector)
    archive = create_backup(tmp_path / "archive", full=True, offline=True)
    name = "extrio_full_restore_" + uuid.uuid4().hex[:12]
    url = pg_store.database_url.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(pg_store.database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        target = source.model_copy(
            update={
                "database_url": url,
                "database_path": tmp_path / "target" / "unused.db",
                "artifact_path": tmp_path / "target" / "artifacts",
                "signing_private_key_path": tmp_path / "target" / "keys" / "signing.pem",
                "credential_encryption_key_path": tmp_path / "target" / "keys" / "credential.key",
            }
        )
        monkeypatch.setattr("extrio.cli.get_settings", lambda: target)
        restore_backup(archive, offline=True)
        restored = Store(target.database_path, database_url=url)
        assert restored.get_collector(collector["id"]) is not None
        sink = restored.list_sinks_for_collector(collector["id"])[0]
        assert restored.get_sink(sink["id"], cipher=CredentialCipher(target.credential_encryption_key_path))["secret"] == "fixture-secret"
        assert (target.artifact_path / "sample.html").read_bytes() == (source.artifact_path / "sample.html").read_bytes()
        assert_history(target, restored, _store, collector)
        with pytest.raises(RuntimeError, match="empty"):
            restore_backup(archive, offline=True)
    finally:
        with psycopg.connect(pg_store.database_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_failed_restore_removes_only_its_partial_outputs(tmp_path, monkeypatch):
    source, _store, _collector = setup_instance(tmp_path / "source", monkeypatch)
    archive = create_backup(tmp_path / "archive", full=True, offline=True)
    target = source.model_copy(
        update={
            "database_path": tmp_path / "target" / "database.db",
            "artifact_path": tmp_path / "target" / "artifacts",
            "signing_private_key_path": tmp_path / "target" / "keys" / "signing.pem",
            "credential_encryption_key_path": tmp_path / "target" / "keys" / "credential.key",
        }
    )
    monkeypatch.setattr("extrio.cli.get_settings", lambda: target)
    import extrio.cli as cli

    copy = cli._copy_file

    def fail_key_copy(source, destination, **kwargs):
        if destination == target.signing_private_key_path:
            raise OSError("fixture disk failure")
        copy(source, destination, **kwargs)

    monkeypatch.setattr(cli, "_copy_file", fail_key_copy)
    with pytest.raises(OSError, match="disk failure"):
        restore_backup(archive, offline=True)
    assert not target.database_path.exists()
    assert not target.artifact_path.exists()
    assert not target.signing_private_key_path.exists()
    assert (archive / "artifacts" / "sample.html").is_file()


def test_cli_crash_during_restore_leaves_startup_blocked(tmp_path, monkeypatch):
    source, store, collector = setup_instance(tmp_path / "source", monkeypatch)
    add_history(source, store, collector)
    archive = create_backup(tmp_path / "archive", full=True, offline=True)
    target = tmp_path / "target"
    env = {
        **os.environ,
        "EXTRIO_DATABASE_URL": "",
        "EXTRIO_DATABASE_PATH": str(target / "database.db"),
        "EXTRIO_ARTIFACT_PATH": str(target / "artifacts"),
        "EXTRIO_SIGNING_PRIVATE_KEY_PATH": str(target / "keys" / "signing.pem"),
        "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": str(target / "keys" / "credential.key"),
        "EXTRIO_SIGNING_KEY_ID": source.signing_key_id,
        "EXTRIO_TENANT_ID": source.tenant_id,
    }
    code = """
import os
import extrio.cli as cli
original = cli._copy_file
def crash_after_copy(source, target, **kwargs):
    original(source, target, **kwargs)
    os._exit(99)
cli._copy_file = crash_after_copy
cli.run_restore()
"""
    result = subprocess.run([sys.executable, "-c", code, str(archive), "--offline"], env=env, capture_output=True, timeout=15)
    assert result.returncode == 99
    from extrio.instance_guard import instance_lock, restore_marker

    assert restore_marker(target / "artifacts").is_file()
    with pytest.raises(RuntimeError, match="incomplete restore"):
        with instance_lock(target / "artifacts"):
            pass
    assert (archive / "artifacts" / "sample.html").is_file()


def test_real_backup_and_restore_cli_roundtrip(tmp_path, monkeypatch):
    source, store, collector = setup_instance(tmp_path / "source", monkeypatch)
    add_history(source, store, collector)
    env = {
        **os.environ,
        "EXTRIO_DATABASE_URL": "",
        "EXTRIO_DATABASE_PATH": str(source.database_path),
        "EXTRIO_ARTIFACT_PATH": str(source.artifact_path),
        "EXTRIO_SIGNING_PRIVATE_KEY_PATH": str(source.signing_private_key_path),
        "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": str(source.credential_encryption_key_path),
        "EXTRIO_SIGNING_KEY_ID": source.signing_key_id,
        "EXTRIO_TENANT_ID": source.tenant_id,
    }
    archive = tmp_path / "cli-archive"
    result = subprocess.run(
        [sys.executable, "-c", "from extrio.cli import run_backup; run_backup()", str(archive), "--offline"],
        env=env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()
    target = source.model_copy(
        update={
            "database_path": tmp_path / "target" / "database.db",
            "artifact_path": tmp_path / "target" / "artifacts",
            "signing_private_key_path": tmp_path / "target" / "keys" / "signing.pem",
            "credential_encryption_key_path": tmp_path / "target" / "keys" / "credential.key",
        }
    )
    for name in ("database_path", "artifact_path", "signing_private_key_path", "credential_encryption_key_path"):
        env["EXTRIO_" + name.upper()] = str(getattr(target, name))
    result = subprocess.run(
        [sys.executable, "-c", "from extrio.cli import run_restore; run_restore()", str(archive), "--offline"],
        env=env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert_history(target, Store(target.database_path, database_url=""), store, collector)
