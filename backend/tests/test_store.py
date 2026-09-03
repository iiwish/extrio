import base64
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from extrio.cli import create_backup, restore_backup
from extrio.credentials import CredentialCipher
from extrio.store import (
    DEFAULT_COLLECTION_POLICY,
    DEFAULT_COLLECTOR_SCHEDULE,
    IdempotencyConflict,
    InvalidCursor,
    Store,
)
from extrio.store_dialect import PostgresDialect, SQLiteDialect, resolve_database


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "extrio.db")
    store.initialize()
    return store


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


def test_async_command_is_durable_and_activates_collector(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    operation = store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"]},
        collector_changes={"status": "exploring"},
    )
    assert store.get_collector(collector["id"])["activeOperationId"] == operation["id"]
    job = store.claim_job(60)
    assert job and job["operationId"] == operation["id"]
    assert Store(store.path).get_operation(operation["id"])["status"] == "queued"


def test_initialize_backfills_ai_history_and_repairs_queued_exploration_payload(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    operation = store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"]},
        collector_changes={"status": "exploring"},
    )

    store.initialize()

    ai_run = store.list_ai_runs()[0]
    assert ai_run["operationId"] == operation["id"]
    assert ai_run["status"] == "queued"
    job = store.claim_job(60)
    assert job is not None
    assert job["payload"]["aiRunId"] == ai_run["id"]


def test_ai_run_keeps_attempts_and_model_invocations_as_auditable_history(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    operation = store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"], "aiRunId": "ai_run_demo"},
        collector_changes={"status": "exploring"},
        ai_run={
            "id": "ai_run_demo",
            "collectorId": collector["id"],
            "collectorName": collector["name"],
            "sourceUrl": collector["sourceUrl"],
            "kind": "rule_generation",
            "trigger": "initial_generation",
            "initiatedBy": "user_demo",
        },
    )

    queued = store.get_ai_run("ai_run_demo")
    assert queued is not None
    assert queued["operationId"] == operation["id"]
    assert queued["status"] == "queued"
    assert queued["reviewStatus"] == "not_ready"
    assert queued["attempts"] == []

    attempt = store.start_ai_attempt("ai_run_demo")
    invocation = store.record_model_invocation(
        ai_run_id="ai_run_demo",
        attempt_id=attempt["id"],
        purpose="discover",
        provider="openai",
        model="gpt-4.1-mini",
        prompt_version="2.0",
        status="succeeded",
        started_at="2026-09-02T00:00:00Z",
        finished_at="2026-09-02T00:00:01Z",
        duration_ms=1000,
        prompt_tokens=120,
        completion_tokens=30,
        response_digest="sha256:" + "a" * 64,
        error=None,
    )
    assert invocation["totalTokens"] == 150
    store.finish_ai_attempt(attempt["id"], status="succeeded", error=None)
    store.update_ai_run(
        "ai_run_demo",
        status="succeeded",
        phase="completed",
        progress=100,
        resultStatus="candidate_ready",
        reviewStatus="ready_review",
        finishedAt="2026-09-02T00:00:02Z",
        durationMs=2000,
    )

    detail = store.get_ai_run("ai_run_demo")
    assert detail is not None
    assert detail["modelSummary"] == {
        "invocationCount": 1,
        "promptTokens": 120,
        "completionTokens": 30,
        "totalTokens": 150,
        "estimatedCost": None,
    }
    assert detail["attempts"][0]["modelInvocations"][0]["purpose"] == "discover"
    assert store.list_ai_runs()[0]["id"] == "ai_run_demo"

    store.mark_latest_ai_run_published(collector["id"], "rule_demo_v1")
    published = store.get_ai_run("ai_run_demo")
    assert published is not None
    assert published["reviewStatus"] == "published"
    assert published["publishedRuleVersionId"] == "rule_demo_v1"


def test_new_ai_candidate_supersedes_previous_pending_review(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")

    for ai_run_id in ("ai_run_first", "ai_run_second"):
        store.create_async_command(
            kind="explore",
            collector_id=collector["id"],
            resource_type="collector",
            resource_id=collector["id"],
            job_payload={"collectorId": collector["id"], "aiRunId": ai_run_id},
            ai_run={
                "id": ai_run_id,
                "collectorId": collector["id"],
                "collectorName": collector["name"],
                "sourceUrl": collector["sourceUrl"],
                "kind": "rule_generation",
                "trigger": "regeneration",
                "initiatedBy": "user_demo",
            },
        )

    store.update_ai_run("ai_run_first", reviewStatus="ready_review")
    store.update_ai_run("ai_run_second", reviewStatus="ready_review")

    assert store.get_ai_run("ai_run_first")["reviewStatus"] == "superseded"
    assert store.get_ai_run("ai_run_second")["reviewStatus"] == "ready_review"


def test_run_reads_expose_stable_creation_timestamp(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    run = {"id": "run_timestamp", "collectorId": collector["id"], "status": "queued"}
    store.save_run(run)

    created = store.get_run(run["id"])
    assert created is not None
    assert created["startedAtIso"].endswith("Z")

    store.save_run({**created, "status": "succeeded"})
    assert store.get_run(run["id"])["startedAtIso"] == created["startedAtIso"]
    assert store.list_runs()[0]["startedAtIso"] == created["startedAtIso"]


def test_idempotency_replays_same_payload_and_rejects_reuse(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.remember_idempotency("scope", "a" * 16, {"x": 1}, 201, {"id": "collector_1"})
    assert store.idempotency_replay("scope", "a" * 16, {"x": 1}) == (201, {"id": "collector_1"})
    with pytest.raises(IdempotencyConflict):
        store.idempotency_replay("scope", "a" * 16, {"x": 2})


def test_collection_policy_versions_are_immutable_and_reset_checkpoint(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    policy_v1 = collector["collectionPolicy"]
    assert policy_v1["version"] == 1
    assert policy_v1["initialWindowDays"] == 30

    checkpoint = {
        "collectorId": collector["id"],
        "policyVersionId": policy_v1["id"],
        "lastSuccessfulRunId": "run_initial",
        "watermark": "2026-08-30",
        "advancedAt": "2026-08-31T00:00:00Z",
    }
    store.save_checkpoint(checkpoint)
    assert store.get_checkpoint(collector["id"]) == checkpoint
    assert store.get_collector(collector["id"])["checkpoint"] == checkpoint

    replacement = {**DEFAULT_COLLECTION_POLICY, "lookbackDays": 7, "maxItems": 500}
    updated = store.create_collection_policy(collector["id"], replacement)
    policy_v2 = updated["collectionPolicy"]
    assert policy_v2["version"] == 2
    assert policy_v2["lookbackDays"] == 7
    assert policy_v2["digest"] != policy_v1["digest"]
    assert updated["checkpoint"] is None
    assert store.get_checkpoint(collector["id"]) is None

    with store.connect() as connection:
        with pytest.raises(Exception, match="immutable"):
            connection.execute(
                "UPDATE collection_policies SET policy_digest=? WHERE id=?",
                ("sha256:" + "0" * 64, policy_v1["id"]),
            )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"mode": "full_scan"}, "fields are invalid"),
        ({"lookbackDays": 91}, "lookbackDays is out of range"),
        ({"initialWindowDays": True}, "initialWindowDays is out of range"),
    ],
)
def test_collection_policy_rejects_unknown_modes_and_out_of_range_values(
    tmp_path: Path, change: dict, message: str
) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    with pytest.raises(ValueError, match=message):
        store.create_collection_policy(collector["id"], {**DEFAULT_COLLECTION_POLICY, **change})


def test_schedule_is_persisted_and_due_occurrences_are_claimed_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    assert collector["schedule"]["enabled"] is False

    scheduled = store.save_schedule(collector["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})["schedule"]
    assert scheduled["revision"] == 2
    assert scheduled["nextRunAt"] is not None

    due = store.claim_due_schedules(datetime(2030, 1, 1, tzinfo=UTC))
    assert len(due) == 1
    assert due[0]["collectorId"] == collector["id"]
    assert store.claim_due_schedules(datetime(2030, 1, 1, tzinfo=UTC)) == []

    store.finish_schedule_occurrence(due[0]["occurrenceKey"], status="skipped", run_id=None, reason="RULE_NOT_PUBLISHED")


def test_schedule_rejects_invalid_cron(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    with pytest.raises(ValueError, match="five-field"):
        store.save_schedule(collector["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "cronExpression": "not a cron"})


def test_published_rule_attestation_and_audit_are_atomic_and_immutable(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
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

    store.ensure_signing_key(signing_key)
    store.publish_rule_bundle(
        collector_id=collector["id"],
        rule_version=rule_version,
        attestation=attestation,
        collector_changes={"status": "published", "activeRuleVersion": "rule_v1"},
        audit={"actorId": "user_rule_reviewer_demo", "action": "rule.published", "requestId": "req_test"},
    )

    assert store.get_rule_version("rule_v1")["ruleDigest"] == rule_version["ruleDigest"]
    assert store.get_rule_attestation("attestation_test")["ruleVersionId"] == "rule_v1"
    assert store.list_audit_events()[0]["action"] == "rule.published"
    with store.connect() as connection:
        with pytest.raises(Exception, match="immutable"):
            connection.execute("UPDATE rule_versions SET rule_digest=? WHERE id='rule_v1'", ("sha256:" + "2" * 64,))
        with pytest.raises(Exception, match="immutable"):
            connection.execute("DELETE FROM rule_attestations WHERE id='attestation_test'")
        with pytest.raises(Exception, match="immutable"):
            connection.execute("DELETE FROM audit_events")

    store.update_signing_key_status(
        "signingkey_test",
        "retired",
        actor_id="security_officer",
        request_id="req_retire",
    )
    assert store.verify_audit_chain("tenant_demo") is True
    with pytest.raises(ValueError, match="retired -> trusted"):
        store.update_signing_key_status(
            "signingkey_test",
            "trusted",
            actor_id="security_officer",
            request_id="req_retrust",
        )


def test_initialize_records_baseline_migration_and_replays_idempotently(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.initialize()
    with store.connect() as connection:
        applied = [str(row["id"]) for row in connection.execute("SELECT id FROM schema_migrations").fetchall()]
    assert applied == ["000_baseline", "001_user_accounts", "002_platform_settings"]


def test_initialize_applies_baseline_to_legacy_pre_migration_database(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    legacy = sqlite3.connect(database)
    legacy.execute(
        "CREATE TABLE collectors (id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    legacy.commit()
    legacy.close()

    store = Store(database)
    store.initialize()
    with store.connect() as connection:
        tables = {str(row["name"]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"deliveries", "delivery_attempts", "sinks", "schema_migrations"}.issubset(tables)


def test_resolve_database_selects_dialect_from_url(tmp_path: Path) -> None:
    fallback = tmp_path / "fallback.db"
    dialect, path = resolve_database(None, fallback)
    assert isinstance(dialect, SQLiteDialect) and path == fallback

    dialect, path = resolve_database("sqlite:///data/x.db", fallback)
    assert isinstance(dialect, SQLiteDialect) and path == Path("data/x.db")

    dialect, path = resolve_database("sqlite:////abs/x.db", fallback)
    assert isinstance(dialect, SQLiteDialect) and path == Path("/abs/x.db")

    dialect, path = resolve_database("postgresql://u:p@h:5432/extrio", fallback)
    assert isinstance(dialect, PostgresDialect) and path == fallback

    with pytest.raises(ValueError, match="unsupported EXTRIO_DATABASE_URL scheme"):
        resolve_database("mysql://u:p@h/db", fallback)


def test_items_cursor_pagination_walks_deterministic_order(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    other = store.create_collector("Other", "Collect notices", "https://other.example.com/list", "other.example.com")
    for run_id in ("run_one", "run_two"):
        store.save_run({"id": run_id, "collectorId": collector["id"], "status": "succeeded"})
    store.save_run({"id": "run_other", "collectorId": other["id"], "status": "succeeded"})

    store.save_items("run_one", [
        make_item("item_a1", collector["id"], "run_one", "2026-09-01 10:00", "e1"),
        make_item("item_a2", collector["id"], "run_one", "2026-09-01 10:00", "e2"),
        make_item("item_a3", collector["id"], "run_one", "2026-09-01 09:00", "e3"),
    ])
    store.save_items("run_two", [make_item("item_b1", collector["id"], "run_two", "2026-09-02 10:00", "e1")])
    store.save_items("run_other", [make_item("item_o1", other["id"], "run_other", "2026-09-03 10:00", "e9")])

    expected_order = ["item_b1", "item_a2", "item_a1", "item_a3"]
    first_page = store.list_items_cursor(collector_id=collector["id"], limit=2)
    assert [item["id"] for item in first_page["items"]] == expected_order[:2]
    assert first_page["nextCursor"] is not None

    second_page = store.list_items_cursor(collector_id=collector["id"], limit=2, cursor=first_page["nextCursor"])
    assert [item["id"] for item in second_page["items"]] == expected_order[2:]
    assert second_page["nextCursor"] is None

    walked = []
    cursor = None
    while True:
        page = store.list_items_cursor(collector_id=collector["id"], limit=1, cursor=cursor)
        walked.extend(item["id"] for item in page["items"])
        if page["nextCursor"] is None:
            break
        cursor = page["nextCursor"]
    assert walked == expected_order

    assert [item["id"] for item in store.list_items_cursor(decision="accepted", limit=10)["items"]].index("item_o1") == 0
    assert store.list_items_cursor(collector_id=collector["id"], decision="rejected", limit=10)["items"] == []
    assert [item["id"] for item in store.list_items_cursor(entity_key="e3", limit=10)["items"]] == ["item_a3"]
    assert [item["id"] for item in store.list_items_cursor(run_id="run_two", limit=10)["items"]] == ["item_b1"]


def test_items_cursor_rejects_invalid_cursor_and_sort_key(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with pytest.raises(InvalidCursor) as invalid:
        store.list_items_cursor(limit=2, cursor="!!!not-a-cursor!!!")
    assert invalid.value.code == "INVALID_CURSOR"
    with pytest.raises(InvalidCursor):
        store.list_items_cursor(limit=2, cursor=base64.urlsafe_b64encode(json.dumps(["2026-09-01", "e1"]).encode()).decode())
    with pytest.raises(ValueError, match="sort key"):
        store.list_items_cursor(sort_key="entity_key")


def test_iter_items_export_streams_same_stable_order(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    store.save_run({"id": "run_one", "collectorId": collector["id"], "status": "succeeded"})
    store.save_items("run_one", [
        make_item("item_a1", collector["id"], "run_one", "2026-09-01 10:00", "e1"),
        make_item("item_a2", collector["id"], "run_one", "2026-09-01 10:00", "e2"),
        make_item("item_a3", collector["id"], "run_one", "2026-09-01 09:00", "e3"),
    ])

    exported = list(store.iter_items_export(collector_id=collector["id"]))
    assert [item["id"] for item in exported] == ["item_a2", "item_a1", "item_a3"]

    walked = []
    cursor = None
    while True:
        page = store.list_items_cursor(collector_id=collector["id"], limit=2, cursor=cursor)
        walked.extend(item["id"] for item in page["items"])
        if page["nextCursor"] is None:
            break
        cursor = page["nextCursor"]
    assert walked == [item["id"] for item in exported]


def test_sink_crud_bumps_version_and_encrypts_secret(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")

    sink = store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/extrio", secret="s3cret")
    assert sink["version"] == 1 and sink["enabled"] is True and sink["secretConfigured"] is True
    assert store.get_sink(sink["id"], cipher=cipher)["secret"] == "s3cret"
    assert store.get_sink(sink["id"])["secretConfigured"] is True and "secret" not in store.get_sink(sink["id"])

    updated = store.update_sink(sink["id"], enabled=False)
    assert updated["version"] == 2 and updated["enabled"] is False
    rekeyed = store.update_sink(sink["id"], cipher=cipher, secret="n3w-s3cret")
    assert rekeyed["version"] == 3
    assert store.get_sink(sink["id"], cipher=cipher)["secret"] == "n3w-s3cret"

    assert [s["id"] for s in store.list_sinks_for_collector(collector["id"])] == [sink["id"]]
    with pytest.raises(ValueError, match="unsupported sink type"):
        store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/x", sink_type="email")
    with pytest.raises(ValueError, match="credential cipher"):
        store.update_sink(sink["id"], secret="orphan")
    with pytest.raises(KeyError):
        store.update_sink("sink_missing", url="https://hooks.example.com/y")

    store.delete_sink(sink["id"])
    assert store.list_sinks_for_collector(collector["id"]) == []
    with pytest.raises(KeyError):
        store.delete_sink(sink["id"])


def test_delivery_state_machine_claims_retries_and_redelivers(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
    sink = store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/extrio", secret="s3cret")

    delivery = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_1")
    assert delivery["status"] == "pending" and delivery["attemptCount"] == 0
    assert delivery["sinkVersionId"] == f"{sink['id']}#v1"
    duplicate = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_1")
    assert duplicate["id"] == delivery["id"]

    base = datetime(2030, 1, 1, tzinfo=UTC)
    claimed = store.claim_due_deliveries(10, now=base, lease_seconds=60)
    assert len(claimed) == 1
    assert claimed[0]["id"] == delivery["id"]
    assert claimed[0]["status"] == "delivering"
    assert claimed[0]["sinkUrl"] == sink["url"]
    assert claimed[0]["leaseUntil"] is not None
    assert store.claim_due_deliveries(10, now=base) == []

    failed = store.record_delivery_attempt(
        delivery["id"],
        status_code=500,
        error="upstream exploded",
        started_at="2030-01-01T00:00:01Z",
        finished_at="2030-01-01T00:00:02Z",
        next_attempt_at="2030-01-01T01:00:00Z",
    )
    assert failed["attemptCount"] == 1 and failed["status"] == "failed"
    assert failed["lastStatusCode"] == 500 and failed["lastError"] == "upstream exploded"
    attempts = store.list_delivery_attempts(delivery["id"])
    assert [attempt["attemptNo"] for attempt in attempts] == [1]

    retried = store.claim_due_deliveries(10, now=base + timedelta(hours=1))
    assert [row["id"] for row in retried] == [delivery["id"]]
    store.record_delivery_attempt(delivery["id"], status_code=200)

    delivered = store.mark_delivery_delivered(delivery["id"])
    assert delivered["status"] == "delivered" and delivered["nextAttemptAt"] is None
    assert store.claim_due_deliveries(10, now=base + timedelta(hours=2)) == []

    stale = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_2")
    assert [row["id"] for row in store.claim_due_deliveries(10, now=base + timedelta(hours=3))] == [stale["id"]]
    # An expired lease makes the stuck delivering row claimable again.
    recovered = store.claim_due_deliveries(10, now=base + timedelta(hours=4))
    assert [row["id"] for row in recovered] == [stale["id"]]
    dead = store.record_delivery_attempt(stale["id"], status_code=410, error="gone")
    dead = store.mark_delivery_dead_lettered(stale["id"], error="gone")
    assert dead["status"] == "dead_lettered" and dead["lastError"] == "gone"

    redelivered = store.redeliver_delivery(stale["id"])
    assert redelivered["id"] == stale["id"]
    assert redelivered["status"] == "pending" and redelivered["redeliveryCount"] == 1
    assert redelivered["attemptCount"] == 1
    assert [attempt["attemptNo"] for attempt in store.list_delivery_attempts(stale["id"])] == [1]
    assert [row["id"] for row in store.claim_due_deliveries(10, now=base + timedelta(hours=5))] == [stale["id"]]

    listed = store.list_deliveries_for_collector(collector["id"])
    assert {row["id"] for row in listed} == {delivery["id"], stale["id"]}
    with pytest.raises(KeyError):
        store.record_delivery_attempt("delivery_missing", status_code=200)
    with pytest.raises(ValueError, match="actively being delivered"):
        store.redeliver_delivery(stale["id"])


def test_backup_and_restore_roundtrip_sqlite(tmp_path: Path) -> None:
    store = make_store(tmp_path / "live")
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    store.save_run({"id": "run_one", "collectorId": collector["id"], "status": "succeeded"})
    store.save_items("run_one", [make_item("item_a1", collector["id"], "run_one", "2026-09-01 10:00", "e1")])

    archive = create_backup(tmp_path / "backup", database_path=store.path)
    assert {path.name for path in archive.iterdir()} == {"backup_manifest.json", "SHA256SUMS", "database.snapshot"}
    manifest = json.loads((archive / "backup_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dialect"] == "sqlite"

    restored_path = tmp_path / "restored" / "extrio.db"
    restore_backup(archive, database_path=restored_path)
    restored = Store(restored_path)
    assert restored.get_collector(collector["id"])["name"] == "Demo"
    assert restored.get_item("item_a1")["entityKey"] == "e1"


def test_backup_restore_rejects_tampered_archive(tmp_path: Path) -> None:
    store = make_store(tmp_path / "live")
    archive = create_backup(tmp_path / "backup", database_path=store.path)
    snapshot = archive / "database.snapshot"
    snapshot.write_bytes(snapshot.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        restore_backup(archive, database_path=tmp_path / "restored" / "extrio.db")


def test_metrics_count_methods_start_empty_and_validate_arguments(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.count_collectors_by_status() == {}
    assert store.count_runs_by_status() == {}
    assert store.count_runs_by_status(within_days=1) == {}
    assert store.count_items_by_decision() == {}
    assert store.count_deliveries_by_status() == {}
    assert store.count_sinks_by_enabled() == {"enabled": 0, "disabled": 0}
    with pytest.raises(ValueError, match="within_days"):
        store.count_runs_by_status(within_days=-1)
    with pytest.raises(ValueError, match="limit"):
        store.recent_run_statuses("collector_any", 0)


def test_metrics_count_methods_aggregate_seeded_rows(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector_a = store.create_collector("Alpha", "Collect notices", "https://a.example.com/list", "a.example.com")
    collector_b = store.create_collector("Beta", "Collect notices", "https://b.example.com/list", "b.example.com")
    assert store.count_collectors_by_status() == {"draft": 2}

    for run_id, status in (("run_m1", "succeeded"), ("run_m2", "failed"), ("run_m3", "succeeded")):
        store.save_run({"id": run_id, "collectorId": collector_a["id"], "status": status})
        time.sleep(0.01)
    store.save_run({"id": "run_m4", "collectorId": collector_b["id"], "status": "cancelled"})
    time.sleep(0.01)

    assert store.count_runs_by_status() == {"succeeded": 2, "failed": 1, "cancelled": 1}
    assert store.count_runs_by_status(within_days=1) == {"succeeded": 2, "failed": 1, "cancelled": 1}

    # Backdate one run past the window (runs.created_at is written by save_run).
    stale_timestamp = (datetime.now(UTC) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    with store.connect() as connection:
        connection.execute("UPDATE runs SET created_at=? WHERE id='run_m3'", (stale_timestamp,))
    assert store.count_runs_by_status(within_days=1) == {"succeeded": 1, "failed": 1, "cancelled": 1}
    assert store.count_runs_by_status() == {"succeeded": 2, "failed": 1, "cancelled": 1}

    store.save_items(
        "run_m1",
        [
            make_item("item_m1", collector_a["id"], "run_m1", "2026-09-01 10:00", "e1"),
            make_item("item_m2", collector_a["id"], "run_m1", "2026-09-01 10:01", "e2", decision="rejected"),
            make_item("item_m3", collector_a["id"], "run_m1", "2026-09-01 10:02", "e3", decision="risk_accepted"),
        ],
    )
    assert store.count_items_by_decision() == {"accepted": 1, "rejected": 1, "risk_accepted": 1}

    cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
    enabled_sink = store.create_sink(collector_a["id"], cipher=cipher, url="https://hooks.example.com/on")
    store.create_sink(collector_a["id"], cipher=cipher, url="https://hooks.example.com/off", enabled=False)
    store.enqueue_delivery(collector_id=collector_a["id"], sink_id=enabled_sink["id"], item_event_id="evt_m_pending")
    delivered = store.enqueue_delivery(collector_id=collector_a["id"], sink_id=enabled_sink["id"], item_event_id="evt_m_done")
    store.mark_delivery_delivered(delivered["id"])
    assert store.count_sinks_by_enabled() == {"enabled": 1, "disabled": 1}
    assert store.count_deliveries_by_status() == {"pending": 1, "delivered": 1}

    assert store.recent_run_statuses(collector_a["id"], 5) == ["failed", "succeeded", "succeeded"]
    assert store.recent_run_statuses(collector_a["id"], 2) == ["failed", "succeeded"]
    assert store.recent_run_statuses(collector_b["id"], 5) == ["cancelled"]
    assert store.recent_run_statuses("collector_missing", 3) == []


def test_list_runs_for_collector_orders_creation_and_filters_window(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    other = store.create_collector("Other", "Collect notices", "https://other.example.com/list", "other.example.com")
    store.save_run({"id": "run_late", "collectorId": collector["id"], "status": "succeeded"})
    store.save_run({"id": "run_early", "collectorId": collector["id"], "status": "failed"})
    store.save_run({"id": "run_other", "collectorId": other["id"], "status": "succeeded"})
    with store.connect() as connection:
        connection.execute("UPDATE runs SET created_at='2026-09-01T08:00:00Z', updated_at='2026-09-01T08:00:00Z' WHERE id='run_early'")
        connection.execute("UPDATE runs SET created_at='2026-09-02T08:00:00Z', updated_at='2026-09-02T08:00:00Z' WHERE id='run_late'")
        connection.execute("UPDATE runs SET created_at='2026-09-02T08:00:00Z', updated_at='2026-09-02T08:00:00Z' WHERE id='run_other'")

    assert [run["id"] for run in store.list_runs_for_collector(collector["id"])] == ["run_early", "run_late"]
    assert [run["id"] for run in store.list_runs_for_collector(collector["id"], since="2026-09-02T00:00:00Z")] == ["run_late"]
    assert [run["id"] for run in store.list_runs_for_collector(collector["id"], until="2026-09-01T23:59:59Z")] == ["run_early"]
    assert store.list_runs_for_collector(collector["id"], since="2026-09-03T00:00:00Z") == []
    assert store.list_runs_for_collector("collector_missing") == []


def test_list_rule_versions_for_collector_pairs_attestations(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    signing_key = {
        "id": "signingkey_test",
        "tenantId": "tenant_demo",
        "status": "trusted",
        "algorithm": "Ed25519",
        "publicKeyPem": "PUBLIC KEY",
        "revision": 1,
        "trustedAt": "2026-08-31T00:00:00Z",
    }
    store.ensure_signing_key(signing_key)
    for version in ("v1", "v2"):
        rule_version = {
            "id": f"rule_demo_{version}",
            "tenantId": "tenant_demo",
            "collectorId": collector["id"],
            "ruleDigest": "sha256:" + "1" * 64,
            "gatherSpec": {"schemaVersion": "extrio.gather.v1"},
            "status": "published",
            "createdAt": "2026-08-31T00:00:00Z",
        }
        attestation = {
            "attestationId": f"attestation_{version}",
            "tenantId": "tenant_demo",
            "ruleVersionId": f"rule_demo_{version}",
            "ruleDigest": rule_version["ruleDigest"],
            "keyId": "signingkey_test",
            "signedAt": "2026-08-31T00:01:00Z",
        }
        store.publish_rule_bundle(
            collector_id=collector["id"],
            rule_version=rule_version,
            attestation=attestation,
            collector_changes={"status": "published", "activeRuleVersion": rule_version["id"]},
            audit={"actorId": "user_rule_reviewer_demo", "action": "rule.published", "requestId": f"req_{version}"},
        )

    versions = store.list_rule_versions_for_collector(collector["id"])
    assert [version["id"] for version in versions] == ["rule_demo_v1", "rule_demo_v2"]
    assert versions[0]["gatherSpec"] == {"schemaVersion": "extrio.gather.v1"}
    assert versions[0]["attestation"]["attestationId"] == "attestation_v1"
    assert versions[1]["attestation"]["ruleVersionId"] == "rule_demo_v2"
    assert store.list_rule_versions_for_collector("collector_missing") == []


def test_list_items_for_collector_window_filters_observed_at(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    other = store.create_collector("Other", "Collect notices", "https://other.example.com/list", "other.example.com")
    store.save_run({"id": "run_one", "collectorId": collector["id"], "status": "succeeded"})
    store.save_run({"id": "run_other", "collectorId": other["id"], "status": "succeeded"})
    store.save_items(
        "run_one",
        [
            make_item("item_a1", collector["id"], "run_one", "2026-09-01T08:30:00Z", "e1"),
            make_item("item_a2", collector["id"], "run_one", "2026-09-01T09:00:00Z", "e2"),
            make_item("item_a3", collector["id"], "run_one", "2026-09-02T08:30:00Z", "e3"),
        ],
    )
    store.save_items("run_other", [make_item("item_o1", other["id"], "run_other", "2026-09-01T08:30:00Z", "e9")])

    exported = [item["id"] for item in store.list_items_for_collector_window(collector["id"])]
    assert exported == ["item_a3", "item_a2", "item_a1"]
    assert [item["id"] for item in store.list_items_for_collector_window(collector["id"], since="2026-09-01T08:45:00Z")] == [
        "item_a3",
        "item_a2",
    ]
    assert [item["id"] for item in store.list_items_for_collector_window(collector["id"], until="2026-09-01T23:59:59Z")] == [
        "item_a2",
        "item_a1",
    ]
    assert [
        item["id"]
        for item in store.list_items_for_collector_window(collector["id"], since="2026-09-01T09:00:00Z", until="2026-09-01T09:00:00Z")
    ] == ["item_a2"]
    assert list(store.list_items_for_collector_window("collector_missing")) == []
