"""Upgrade real baseline databases and recover pre-upgrade state with matching code."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from extrio.auth import verify_password
from extrio.credentials import CredentialCipher
from extrio.integrity import verify_attestation_signature
from extrio.store import Store

BASELINE = "86ebcc4b570f8b5b5acf3f1c6ba0f70ac7ed42f7"
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "release_baseline.py"


@pytest.fixture
def baseline(tmp_path):
    result = subprocess.run(["git", "archive", BASELINE, "backend", "docs/contracts"], cwd=ROOT, capture_output=True, check=True)
    target = tmp_path / "baseline"
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(target, filter="data")
    return target


@pytest.fixture(params=["sqlite", "postgresql"])
def databases(request):
    if request.param == "sqlite":
        yield "", ""
        return
    base = os.environ.get("EXTRIO_TEST_DATABASE_URL")
    if not base:
        pytest.skip("Requires an explicitly isolated EXTRIO_TEST_DATABASE_URL")
    names = ["extrio_release_" + uuid.uuid4().hex[:12] for _ in range(2)]
    created = []
    try:
        with psycopg.connect(base, autocommit=True) as admin:
            for name in names:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)
        yield tuple(base.rsplit("/", 1)[0] + "/" + name for name in names)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            for name in created:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def environment(code, root, database_url):
    return {
        **os.environ,
        "PYTHONPATH": str(code / "backend/src"),
        "EXTRIO_DATABASE_URL": database_url,
        "EXTRIO_DATABASE_PATH": str(root / "database.db"),
        "EXTRIO_ARTIFACT_PATH": str(root / "artifacts"),
        "EXTRIO_CONTRACTS_PATH": str(code / "docs/contracts"),
        "EXTRIO_SEED_DEMO": "false",
        "EXTRIO_SIGNING_PRIVATE_KEY_PATH": str(root / "keys/signing.pem"),
        "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": str(root / "keys/credential.key"),
    }


def old_process(code, env, arguments):
    result = subprocess.run([sys.executable, *arguments], cwd=code, env=env, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode()


def test_concurrent_empty_database_startup_serializes_migrations(databases, tmp_path):
    import time

    database_url, _ = databases
    env = environment(ROOT, tmp_path, database_url)
    code = """
import sys, time
from pathlib import Path
from extrio.config import get_settings
from extrio.store import Store
settings = get_settings()
store = Store(settings.database_path, database_url=settings.database_url)
original = store.dialect.run_script
def delayed(connection, script):
    time.sleep(0.15)
    original(connection, script)
store.dialect.run_script = delayed
Path(sys.argv[1]).touch()
while not Path(sys.argv[2]).exists():
    time.sleep(0.01)
store.initialize()
"""
    gate = tmp_path / "start"
    processes = []
    try:
        for number in range(2):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", code, str(tmp_path / f"ready-{number}"), str(gate)],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        deadline = time.monotonic() + 15
        while not all((tmp_path / f"ready-{number}").exists() for number in range(2)):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        gate.touch()
        results = [process.communicate(timeout=30) for process in processes]
        assert [process.returncode for process in processes] == [0, 0], [stderr.decode() for _, stderr in results]
        store = Store(tmp_path / "database.db", database_url=database_url)
        store.initialize()
        with store.connect() as connection:
            applied = [row["id"] for row in connection.execute("SELECT id FROM schema_migrations").fetchall()]
        assert len(applied) == len(set(applied))
        assert any(m.startswith("008") for m in applied)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_baseline_upgrade_preserves_history_and_matching_release_rollback(baseline, databases, tmp_path):
    source_url, target_url = databases
    source, target = tmp_path / "source", tmp_path / "rollback"
    source.mkdir()
    env = environment(baseline, source, source_url)
    before_file = tmp_path / "before.json"
    old_process(baseline, env, [str(FIXTURE), "seed", str(before_file)])
    before = json.loads(before_file.read_text())
    assert not any(m.startswith("004") for m in before["migrations"])

    # The baseline CLI only backs up the database; bundle its keys and artifacts separately.
    backup = tmp_path / "pre-upgrade"
    old_process(baseline, env, ["-c", "from extrio.cli import run_backup; run_backup()", str(backup / "database")])
    for directory in ("artifacts", "keys"):
        shutil.copytree(source / directory, backup / directory)
    checksums = {str(p.relative_to(backup)): hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.rglob("*") if p.is_file()}

    upgraded = Store(source / "database.db", database_url=source_url)
    upgraded.initialize()
    upgraded.initialize()
    collector = upgraded.get_collector(before["collector"]["id"])
    assert collector["collectionVersion"] == before["collector"]["collectionVersion"] == "tender_notice_v4"
    assert collector["activeRuleVersion"] == "rule_release_2"
    assert [{k: v for k, v in item.items() if k != "collectionAttribution"} for item in upgraded.list_items()] == before["items"]
    assert {k: v for k, v in upgraded.get_run("run_release").items() if k != "collectionAttribution"} == before["run"]
    assert upgraded.get_run("run_release")["collectionAttribution"]["collectionId"] == collector["collectionId"]
    with upgraded.connect() as connection:
        assert [upgraded._decode(row) for row in connection.execute("SELECT data FROM items").fetchall()] == before["items"]
    for original in before["rules"]:
        assert upgraded.get_rule_version(original["id"]) == original
    for attestation in before["attestations"]:
        verify_attestation_signature(attestation, upgraded.get_signing_key(attestation["keyId"])["publicKeyPem"])
    assert upgraded.get_auth_session("release-fixture-session") == before["session"]
    assert verify_password("Release-fixture-123!", upgraded.get_auth_credentials("release-admin")["passwordHash"])
    sink = upgraded.list_sinks_for_collector(collector["id"])[0]
    assert upgraded.get_sink(sink["id"], cipher=CredentialCipher(source / "keys/credential.key"))["secret"] == "release-fixture-secret"
    assert upgraded.verify_audit_chain(before["rules"][0]["tenantId"])
    with upgraded.connect() as connection:
        assert any(row["id"].startswith("008") for row in connection.execute("SELECT id FROM schema_migrations").fetchall())

    collection = upgraded.get_collection(collector["collectionId"])
    changed = upgraded.change_collection(
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
    upgraded.publish_collection_version(collection["id"], changed["revision"], before["user"]["id"])
    assert upgraded.get_collector(collector["id"])["collectionVersion"] == "tender_notice_v4"
    assert upgraded.collector_compilation_context(collector).get("frozenCollectionVersion") is None

    for name, digest in checksums.items():
        assert hashlib.sha256((backup / name).read_bytes()).hexdigest() == digest
    target_env = environment(baseline, target, target_url)
    old_process(baseline, target_env, ["-c", "from extrio.cli import run_restore; run_restore()", str(backup / "database")])
    for directory in ("artifacts", "keys"):
        shutil.copytree(backup / directory, target / directory)
    restored_file = tmp_path / "restored.json"
    old_process(baseline, target_env, [str(FIXTURE), "inspect", str(restored_file)])
    assert json.loads(restored_file.read_text()) == before
    for directory in ("artifacts", "keys"):
        for path in (backup / directory).rglob("*"):
            if path.is_file():
                assert (target / path.relative_to(backup)).read_bytes() == path.read_bytes()
