from datetime import UTC, datetime
from pathlib import Path

import pytest

from extrio.store import DEFAULT_COLLECTION_POLICY, DEFAULT_COLLECTOR_SCHEDULE, IdempotencyConflict, Store


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "extrio.db")
    store.initialize()
    return store


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
