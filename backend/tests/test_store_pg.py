"""PostgreSQL dialect suite for the Extrio store.

Skips gracefully when no PostgreSQL test server is reachable. Point
EXTRIO_TEST_DATABASE_URL at a disposable instance, e.g.:

    docker run -d --name extrio-pg-test -e POSTGRES_PASSWORD=extrio_test \
        -p 5433:5432 postgres:16-alpine
    EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_test@127.0.0.1:5433/postgres \
        uv run --project backend pytest backend/tests/test_store_pg.py
"""

import os
import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from extrio.cli import create_backup, restore_backup
from extrio.credentials import CredentialCipher
from extrio.store import IdempotencyConflict, InvalidCursor, Store, UsernameTaken

TEST_DATABASE_URL = os.environ.get(
    "EXTRIO_TEST_DATABASE_URL",
    "postgresql://postgres:extrio_test@127.0.0.1:5433/postgres",
)


def _postgres_available() -> bool:
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason=f"PostgreSQL test server unreachable at {TEST_DATABASE_URL}",
)


@pytest.fixture
def pg_store(tmp_path: Path):
    database_name = f"extrio_test_{uuid.uuid4().hex[:12]}"
    base_url = TEST_DATABASE_URL.rsplit("/", 1)[0]
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True, connect_timeout=3) as admin:
        admin.execute(f'CREATE DATABASE "{database_name}"')
    store = Store(tmp_path / "pg.db", database_url=f"{base_url}/{database_name}")
    store.initialize()
    yield store
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True, connect_timeout=3) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


def make_item(
    item_id: str,
    collector_id: str,
    run_id: str,
    observed_at: str,
    entity_key: str,
    decision: str = "accepted",
) -> dict:
    return {
        "id": item_id,
        "collectorId": collector_id,
        "runId": run_id,
        "decision": decision,
        "entityKey": entity_key,
        "observedAt": observed_at,
        "lineage": {"runId": run_id},
    }


def test_initialize_applies_baseline_migrations_idempotently(pg_store: Store) -> None:
    pg_store.initialize()
    with pg_store.connect() as connection:
        applied = [str(row["id"]) for row in connection.execute("SELECT id FROM schema_migrations").fetchall()]
        tables = {str(row["table_name"]) for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ).fetchall()}
    assert applied == ["000_baseline", "001_user_accounts"]
    assert {"sinks", "deliveries", "delivery_attempts", "audit_events", "collector_schedules"}.issubset(tables)


def test_collector_crud_and_source_url_json_extraction(pg_store: Store) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    assert pg_store.get_collector(collector["id"])["name"] == "Demo"
    assert pg_store.source_exists("https://example.com/list") is True
    assert pg_store.source_exists("https://example.com/other") is False
    assert pg_store.source_exists("https://example.com/list", exclude_collector_id=collector["id"]) is False

    collector["name"] = "Renamed"
    pg_store.save_collector(collector)
    assert pg_store.list_collectors()[0]["name"] == "Renamed"


def test_auth_usernames_match_case_insensitively(pg_store: Store) -> None:
    pg_store.create_first_auth_user(username="Admin", display_name="Root", password_hash="hash")
    credentials = pg_store.get_auth_credentials("admin")
    assert credentials is not None and credentials["username"] == "Admin"
    with pytest.raises(psycopg.errors.UniqueViolation):
        with pg_store.transaction() as connection:
            connection.execute(
                "INSERT INTO auth_users(id, username, password_hash, role, display_name, created_at, updated_at)"
                " VALUES('user_x', 'ADMIN', 'h', 'administrator', 'Dup', '2026-01-01', '2026-01-01')"
            )


def test_user_crud_and_enabled_flag_roundtrip(pg_store: Store) -> None:
    pg_store.create_first_auth_user(username="root", display_name="Root", password_hash="hash")
    engineer = pg_store.create_user(
        username="Engineer",
        password_hash="hash2",
        role="engineer",
        display_name="Eng",
    )
    assert engineer["username"] == "Engineer"
    assert engineer["role"] == "engineer"
    assert engineer["enabled"] is True
    assert "passwordHash" not in engineer
    assert {"createdAt", "updatedAt"}.issubset(engineer)

    with pytest.raises(UsernameTaken) as taken:
        pg_store.create_user(username="engineer", password_hash="hash3", role="viewer", display_name="Dup")
    assert taken.value.code == "USERNAME_TAKEN"

    updated = pg_store.update_user(engineer["id"], display_name="Renamed", enabled=False)
    assert updated["displayName"] == "Renamed" and updated["enabled"] is False
    assert pg_store.get_user(engineer["id"])["enabled"] is False
    with pytest.raises(KeyError):
        pg_store.update_user("user_missing", display_name="Nobody")

    credentials = pg_store.get_auth_credentials("ENGINEER")
    assert credentials is not None and credentials["enabled"] is False
    pg_store.update_user_password(engineer["id"], "new-hash")
    assert pg_store.get_auth_credentials("engineer")["passwordHash"] == "new-hash"

    assert pg_store.count_active_administrators() == 1
    pg_store.update_user(engineer["id"], role="administrator", enabled=True)
    assert pg_store.count_active_administrators() == 2
    assert [user["username"] for user in pg_store.list_users()] == ["root", "Engineer"]


def test_job_lease_lifecycle(pg_store: Store) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    operation = pg_store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"]},
    )
    job = pg_store.claim_job(60)
    assert job is not None and job["operationId"] == operation["id"]
    assert job["payload"]["collectorId"] == collector["id"]
    pg_store.finish_job(job["id"])
    assert pg_store.claim_job(60) is None


def test_schedule_claims_use_boolean_columns(pg_store: Store) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    schedule_values = {"enabled": True, "cronExpression": "0 8 * * *", "timezone": "Asia/Shanghai", "overlapPolicy": "forbid"}
    scheduled = pg_store.save_schedule(collector["id"], schedule_values)["schedule"]
    assert scheduled["enabled"] is True
    due = pg_store.claim_due_schedules(datetime(2030, 1, 1, tzinfo=UTC))
    assert len(due) == 1 and due[0]["collectorId"] == collector["id"]
    assert pg_store.claim_due_schedules(datetime(2030, 1, 1, tzinfo=UTC)) == []


def test_idempotency_and_platform_settings_roundtrip(pg_store: Store) -> None:
    pg_store.remember_idempotency("scope", "a" * 16, {"x": 1}, 201, {"id": "collector_1"})
    assert pg_store.idempotency_replay("scope", "a" * 16, {"x": 1}) == (201, {"id": "collector_1"})
    with pytest.raises(IdempotencyConflict):
        pg_store.idempotency_replay("scope", "a" * 16, {"x": 2})

    saved = pg_store.save_platform_setting("model", {"provider": "openai"})
    assert pg_store.get_platform_setting("model") == saved


def test_rule_publication_triggers_enforce_immutability(pg_store: Store) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    signing_key = {
        "id": "signingkey_test",
        "tenantId": "tenant_demo",
        "status": "trusted",
        "algorithm": "Ed25519",
        "publicKeyPem": "PUBLIC KEY",
        "revision": 1,
        "trustedAt": "2026-08-31T00:00:00Z",
    }
    rule_version = {
        "id": "rule_v1",
        "tenantId": "tenant_demo",
        "collectorId": collector["id"],
        "ruleDigest": "sha256:" + "1" * 64,
        "gatherSpec": {"schemaVersion": "extrio.gather.v1"},
        "status": "published",
        "createdAt": "2026-08-31T00:00:00Z",
    }
    attestation = {
        "attestationId": "attestation_test",
        "tenantId": "tenant_demo",
        "ruleVersionId": "rule_v1",
        "ruleDigest": rule_version["ruleDigest"],
        "keyId": "signingkey_test",
        "signedAt": "2026-08-31T00:01:00Z",
    }
    pg_store.ensure_signing_key(signing_key)
    pg_store.publish_rule_bundle(
        collector_id=collector["id"],
        rule_version=rule_version,
        attestation=attestation,
        collector_changes={"status": "published", "activeRuleVersion": "rule_v1"},
        audit={"actorId": "user_rule_reviewer_demo", "action": "rule.published", "requestId": "req_test"},
    )
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with pg_store.transaction() as connection:
            connection.execute("UPDATE rule_versions SET rule_digest='x' WHERE id='rule_v1'")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with pg_store.transaction() as connection:
            connection.execute("DELETE FROM audit_events")
    assert pg_store.verify_audit_chain("tenant_demo") is True


def test_items_cursor_pagination_walks_deterministic_order(pg_store: Store) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    other = pg_store.create_collector("Other", "Collect notices", "https://other.example.com/list", "other.example.com")
    for run_id in ("run_one", "run_two"):
        pg_store.save_run({"id": run_id, "collectorId": collector["id"], "status": "succeeded"})
    pg_store.save_run({"id": "run_other", "collectorId": other["id"], "status": "succeeded"})

    pg_store.save_items("run_one", [
        make_item("item_a1", collector["id"], "run_one", "2026-09-01 10:00", "e1"),
        make_item("item_a2", collector["id"], "run_one", "2026-09-01 10:00", "e2"),
        make_item("item_a3", collector["id"], "run_one", "2026-09-01 09:00", "e3"),
    ])
    pg_store.save_items("run_two", [make_item("item_b1", collector["id"], "run_two", "2026-09-02 10:00", "e1")])
    pg_store.save_items("run_other", [make_item("item_o1", other["id"], "run_other", "2026-09-03 10:00", "e9")])

    expected_order = ["item_b1", "item_a2", "item_a1", "item_a3"]
    first_page = pg_store.list_items_cursor(collector_id=collector["id"], limit=2)
    assert [item["id"] for item in first_page["items"]] == expected_order[:2]

    second_page = pg_store.list_items_cursor(collector_id=collector["id"], limit=2, cursor=first_page["nextCursor"])
    assert [item["id"] for item in second_page["items"]] == expected_order[2:]
    assert second_page["nextCursor"] is None

    assert [item["id"] for item in pg_store.list_items_cursor(entity_key="e3", limit=10)["items"]] == ["item_a3"]
    assert [item["id"] for item in pg_store.list_items_cursor(decision="accepted", limit=1)["items"]] == ["item_o1"]
    exported = [item["id"] for item in pg_store.iter_items_export(collector_id=collector["id"])]
    assert exported == expected_order

    with pytest.raises(InvalidCursor) as invalid:
        pg_store.list_items_cursor(limit=2, cursor="!!!not-a-cursor!!!")
    assert invalid.value.code == "INVALID_CURSOR"


def test_sink_crud_bumps_version_and_encrypts_secret(pg_store: Store, tmp_path: Path) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")

    sink = pg_store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/extrio", secret="s3cret")
    assert sink["version"] == 1 and sink["enabled"] is True
    assert pg_store.get_sink(sink["id"], cipher=cipher)["secret"] == "s3cret"

    updated = pg_store.update_sink(sink["id"], cipher=cipher, url="https://hooks.example.com/v2", secret="n3w")
    assert updated["version"] == 2 and updated["url"] == "https://hooks.example.com/v2"
    assert pg_store.get_sink(sink["id"], cipher=cipher)["secret"] == "n3w"
    assert [s["id"] for s in pg_store.list_sinks_for_collector(collector["id"])] == [sink["id"]]

    with pytest.raises(ValueError, match="unsupported sink type"):
        pg_store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/x", sink_type="email")
    pg_store.delete_sink(sink["id"])
    assert pg_store.list_sinks_for_collector(collector["id"]) == []


def test_delivery_state_machine_claims_retries_and_redelivers(pg_store: Store, tmp_path: Path) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
    sink = pg_store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/extrio", secret="s3cret")

    delivery = pg_store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_1")
    assert delivery["status"] == "pending" and delivery["sinkVersionId"] == f"{sink['id']}#v1"
    duplicate = pg_store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_1")
    assert duplicate["id"] == delivery["id"]

    base = datetime(2030, 1, 1, tzinfo=UTC)
    claimed = pg_store.claim_due_deliveries(10, now=base, lease_seconds=60)
    assert [row["id"] for row in claimed] == [delivery["id"]]
    assert claimed[0]["status"] == "delivering"
    assert claimed[0]["sinkUrl"] == sink["url"]
    assert pg_store.claim_due_deliveries(10, now=base) == []

    failed = pg_store.record_delivery_attempt(
        delivery["id"],
        status_code=500,
        error="upstream exploded",
        next_attempt_at="2030-01-01T01:00:00Z",
    )
    assert failed["attemptCount"] == 1 and failed["status"] == "failed"
    assert [attempt["attemptNo"] for attempt in pg_store.list_delivery_attempts(delivery["id"])] == [1]

    retried = pg_store.claim_due_deliveries(10, now=base + timedelta(hours=1))
    assert [row["id"] for row in retried] == [delivery["id"]]
    pg_store.record_delivery_attempt(delivery["id"], status_code=200)
    delivered = pg_store.mark_delivery_delivered(delivery["id"])
    assert delivered["status"] == "delivered" and delivered["nextAttemptAt"] is None

    stale = pg_store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_2")
    assert [row["id"] for row in pg_store.claim_due_deliveries(10, now=base + timedelta(hours=3))] == [stale["id"]]
    # An expired lease makes the stuck delivering row claimable again.
    recovered = pg_store.claim_due_deliveries(10, now=base + timedelta(hours=4))
    assert [row["id"] for row in recovered] == [stale["id"]]
    pg_store.record_delivery_attempt(stale["id"], status_code=410, error="gone")
    dead = pg_store.mark_delivery_dead_lettered(stale["id"], error="gone")
    assert dead["status"] == "dead_lettered"

    redelivered = pg_store.redeliver_delivery(stale["id"])
    assert redelivered["status"] == "pending" and redelivered["redeliveryCount"] == 1
    assert redelivered["attemptCount"] == 1
    assert [row["id"] for row in pg_store.claim_due_deliveries(10, now=base + timedelta(hours=5))] == [stale["id"]]

    listed = pg_store.list_deliveries_for_collector(collector["id"])
    assert {row["id"] for row in listed} == {delivery["id"], stale["id"]}
    with pytest.raises(KeyError):
        pg_store.record_delivery_attempt("delivery_missing", status_code=200)


def test_metrics_count_methods_aggregate_seeded_rows_on_postgres(pg_store: Store, tmp_path: Path) -> None:
    collector_a = pg_store.create_collector("Alpha", "Collect notices", "https://a.example.com/list", "a.example.com")
    collector_b = pg_store.create_collector("Beta", "Collect notices", "https://b.example.com/list", "b.example.com")
    assert pg_store.count_collectors_by_status() == {"draft": 2}

    for run_id, status in (("run_pg1", "succeeded"), ("run_pg2", "failed"), ("run_pg3", "succeeded")):
        pg_store.save_run({"id": run_id, "collectorId": collector_a["id"], "status": status})
        time.sleep(0.01)

    assert pg_store.count_runs_by_status() == {"succeeded": 2, "failed": 1}
    assert pg_store.count_runs_by_status(within_days=1) == {"succeeded": 2, "failed": 1}
    assert pg_store.recent_run_statuses(collector_a["id"], 2) == ["succeeded", "failed"]
    assert pg_store.recent_run_statuses(collector_b["id"], 5) == []

    pg_store.save_items(
        "run_pg1",
        [
            make_item("item_pg1", collector_a["id"], "run_pg1", "2026-09-01 10:00", "e1"),
            make_item("item_pg2", collector_a["id"], "run_pg1", "2026-09-01 10:01", "e2", decision="rejected"),
        ],
    )
    assert pg_store.count_items_by_decision() == {"accepted": 1, "rejected": 1}

    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
    enabled_sink = pg_store.create_sink(collector_a["id"], cipher=cipher, url="https://hooks.example.com/on")
    pg_store.create_sink(collector_a["id"], cipher=cipher, url="https://hooks.example.com/off", enabled=False)
    delivered = pg_store.enqueue_delivery(collector_id=collector_a["id"], sink_id=enabled_sink["id"], item_event_id="evt_pg1")
    pg_store.mark_delivery_delivered(delivered["id"])
    pg_store.enqueue_delivery(collector_id=collector_a["id"], sink_id=enabled_sink["id"], item_event_id="evt_pg2")
    assert pg_store.count_sinks_by_enabled() == {"enabled": 1, "disabled": 1}
    assert pg_store.count_deliveries_by_status() == {"pending": 1, "delivered": 1}


def test_backup_restore_roundtrip_postgresql(pg_store: Store, tmp_path: Path) -> None:
    if shutil.which("pg_dump") is None or shutil.which("pg_restore") is None:
        pytest.skip("pg_dump/pg_restore client tools are not installed")
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    pg_store.save_run({"id": "run_one", "collectorId": collector["id"], "status": "succeeded"})
    pg_store.save_items("run_one", [make_item("item_a1", collector["id"], "run_one", "2026-09-01 10:00", "e1")])

    archive = create_backup(tmp_path / "backup", database_url=pg_store.database_url)
    assert {path.name for path in archive.iterdir()} == {"backup_manifest.json", "SHA256SUMS", "database.pg_dump"}

    restore_database_name = f"extrio_restore_{uuid.uuid4().hex[:8]}"
    restored = f"{pg_store.database_url.rsplit('/', 1)[0]}/{restore_database_name}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True, connect_timeout=3) as admin:
        admin.execute(f'CREATE DATABASE "{restore_database_name}"')
    try:
        restore_backup(archive, database_url=restored)
        target = Store(tmp_path / "pg.db", database_url=restored)
        assert target.get_collector(collector["id"])["name"] == "Demo"
        assert target.get_item("item_a1")["entityKey"] == "e1"
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True, connect_timeout=3) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{restore_database_name}" WITH (FORCE)')


def test_evidence_store_queries_filter_windows_and_pair_attestations(pg_store: Store) -> None:
    collector = pg_store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    other = pg_store.create_collector("Other", "Collect notices", "https://other.example.com/list", "other.example.com")
    pg_store.save_run({"id": "run_early", "collectorId": collector["id"], "status": "succeeded"})
    pg_store.save_run({"id": "run_late", "collectorId": collector["id"], "status": "succeeded"})
    pg_store.save_run({"id": "run_other", "collectorId": other["id"], "status": "succeeded"})
    with pg_store.connect() as connection:
        connection.execute("UPDATE runs SET created_at='2026-09-01T08:00:00Z', updated_at='2026-09-01T08:00:00Z' WHERE id='run_early'")
        connection.execute("UPDATE runs SET created_at='2026-09-02T08:00:00Z', updated_at='2026-09-02T08:00:00Z' WHERE id='run_late'")
        connection.execute("UPDATE runs SET created_at='2026-09-02T08:00:00Z', updated_at='2026-09-02T08:00:00Z' WHERE id='run_other'")

    assert [run["id"] for run in pg_store.list_runs_for_collector(collector["id"])] == ["run_early", "run_late"]
    assert [run["id"] for run in pg_store.list_runs_for_collector(collector["id"], since="2026-09-02T00:00:00Z")] == ["run_late"]
    assert [run["id"] for run in pg_store.list_runs_for_collector(collector["id"], until="2026-09-01T23:59:59Z")] == ["run_early"]
    assert pg_store.list_runs_for_collector("collector_missing") == []

    signing_key = {
        "id": "signingkey_test",
        "tenantId": "tenant_demo",
        "status": "trusted",
        "algorithm": "Ed25519",
        "publicKeyPem": "PUBLIC KEY",
        "revision": 1,
        "trustedAt": "2026-08-31T00:00:00Z",
    }
    pg_store.ensure_signing_key(signing_key)
    rule_version = {
        "id": "rule_demo_v1",
        "tenantId": "tenant_demo",
        "collectorId": collector["id"],
        "ruleDigest": "sha256:" + "1" * 64,
        "gatherSpec": {"schemaVersion": "extrio.gather.v1"},
        "status": "published",
        "createdAt": "2026-08-31T00:00:00Z",
    }
    attestation = {
        "attestationId": "attestation_pg_v1",
        "tenantId": "tenant_demo",
        "ruleVersionId": "rule_demo_v1",
        "ruleDigest": rule_version["ruleDigest"],
        "keyId": "signingkey_test",
        "signedAt": "2026-08-31T00:01:00Z",
    }
    pg_store.publish_rule_bundle(
        collector_id=collector["id"],
        rule_version=rule_version,
        attestation=attestation,
        collector_changes={"status": "published", "activeRuleVersion": "rule_demo_v1"},
        audit={"actorId": "user_rule_reviewer_demo", "action": "rule.published", "requestId": "req_pg"},
    )
    versions = pg_store.list_rule_versions_for_collector(collector["id"])
    assert [version["id"] for version in versions] == ["rule_demo_v1"]
    assert versions[0]["gatherSpec"] == {"schemaVersion": "extrio.gather.v1"}
    assert versions[0]["attestation"]["attestationId"] == "attestation_pg_v1"

    pg_store.save_items(
        "run_early",
        [
            make_item("item_a1", collector["id"], "run_early", "2026-09-01T08:30:00Z", "e1"),
            make_item("item_a2", collector["id"], "run_early", "2026-09-01T09:00:00Z", "e2"),
            make_item("item_a3", collector["id"], "run_early", "2026-09-02T08:30:00Z", "e3"),
        ],
    )
    pg_store.save_items("run_other", [make_item("item_o1", other["id"], "run_other", "2026-09-01T08:30:00Z", "e9")])
    exported = [item["id"] for item in pg_store.list_items_for_collector_window(collector["id"])]
    assert exported == ["item_a3", "item_a2", "item_a1"]
    assert [item["id"] for item in pg_store.list_items_for_collector_window(collector["id"], since="2026-09-01T08:45:00Z")] == [
        "item_a3",
        "item_a2",
    ]
    assert [item["id"] for item in pg_store.list_items_for_collector_window(collector["id"], until="2026-09-01T23:59:59Z")] == [
        "item_a2",
        "item_a1",
    ]
    assert list(pg_store.list_items_for_collector_window("collector_missing")) == []
