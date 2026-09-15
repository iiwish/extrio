import pytest
from jsonschema import Draft202012Validator
from test_collection_versions import client, command  # noqa: F401, F811 - pytest fixture registration
from test_users import PASSWORDS, login_client, make_user, user_store  # noqa: F401, F811 - pytest fixture registration

import extrio.app as app_module


def source():
    return app_module.store.create_collector("Lifecycle", "Collect", "https://example.com/lifecycle", "example.com")


def validate_schema(name, payload):
    Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": app_module.contracts.openapi["components"]}).validate(
        payload
    )


def test_management_api_responses_match_generated_contract(client):
    from test_collector_reassignment import move, plan, target

    value = source()
    validate_schema("CollectorLifecyclePlan", preview(client, value))
    result = manage(client, value, "archive", "contract-archive").json()
    validate_schema("CollectorLifecycleResult", result)
    result = manage(client, value, "restore", "contract-restore").json()
    validate_schema("CollectorLifecycleResult", result)
    destination = target(client)
    planned = plan(client, value, destination)
    validate_schema("CollectorReassignmentPlan", planned)
    validate_schema("CollectorDetail", move(client, value, destination, planned).json())
    empty = app_module.store.create_collector("Empty", "Collect", "https://example.com/empty-contract", "example.com")
    validate_schema("CollectorLifecycleResult", manage(client, empty, "delete", "contract-delete-01").json())


def test_archived_published_sources_are_not_counted_as_executable(client):
    from test_collector_reassignment import published

    value = published(client)
    before = client.get("/api/v1/overview").json()["collectors"]
    assert before["published"] == 1
    assert manage(client, value, "archive", "overview-archive-key").status_code == 200
    after = client.get("/api/v1/overview").json()["collectors"]
    assert after["published"] == 0
    assert after["total"] == before["total"]
    assert app_module.store.get_collection(value["collectionId"])["publishedSourceCount"] == 0


def preview(client, value):
    response = client.get(f"/api/v1/collectors/{value['id']}/lifecycle")
    assert response.status_code == 200
    return response.json()


def manage(client, value, action, key="lifecycle-command-key"):
    plan = preview(client, value)
    return command(client, "POST", f"/api/v1/collectors/{value['id']}/lifecycle", {"action": action, "planDigest": plan["planDigest"]}, key)


def test_empty_delete_is_atomic_and_replayable(client):
    value = source()
    plan = preview(client, value)
    assert plan["deleteBlockers"] == []
    body = {"action": "delete", "planDigest": plan["planDigest"]}
    path = f"/api/v1/collectors/{value['id']}/lifecycle"
    response = command(client, "POST", path, body)
    assert response.status_code == 200
    assert app_module.store.get_collector(value["id"]) is None
    repeated = command(client, "POST", path, body)
    assert repeated.json() == response.json()
    assert repeated.headers["Idempotency-Replayed"] == "true"


def test_archive_restore_and_core_execution_gate(client):
    value = source()
    assert manage(client, value, "archive").status_code == 200
    current = app_module.store.get_collector(value["id"])
    assert current["lifecycle"] == "archived"
    assert current["schedule"]["enabled"] is False
    assert value["id"] not in [item["id"] for item in client.get("/api/v1/collectors").json()["items"]]
    assert value["id"] in [item["id"] for item in client.get("/api/v1/collectors?lifecycle=archived").json()["items"]]
    with pytest.raises(ValueError, match="COLLECTOR_ARCHIVED"):
        app_module.store.create_async_command(
            kind="explore",
            collector_id=value["id"],
            resource_type="collector",
            resource_id=value["id"],
            job_payload={},
            activate_collector=False,
        )
    with pytest.raises(ValueError, match="COLLECTOR_ARCHIVED"):
        app_module.store.save_schedule(
            value["id"],
            {k: (True if k == "enabled" else current["schedule"][k]) for k in ("enabled", "cronExpression", "timezone", "overlapPolicy")},
        )
    assert manage(client, value, "restore", "restore-command-key").status_code == 200
    assert app_module.store.get_collector(value["id"])["schedule"]["enabled"] is False


def test_durable_queue_blocks_even_with_missing_active_pointer(client):
    value = source()
    app_module.store.create_async_command(
        kind="explore", collector_id=value["id"], resource_type="collector", resource_id=value["id"], job_payload={}
    )
    value = app_module.store.get_collector(value["id"])
    value["activeOperationId"] = None
    app_module.store.save_collector(value)
    plan = preview(client, value)
    assert "TASK_ALREADY_ACTIVE" in plan["blockers"]
    assert "TASK_ALREADY_ACTIVE" in plan["deleteBlockers"]
    assert plan["historyCounts"]["operations"] == 1
    assert manage(client, value, "archive").status_code == 409
    assert manage(client, value, "delete").status_code == 409


def test_stale_preview_and_audit_failure_leave_source_intact(client, monkeypatch):
    value = source()
    plan = preview(client, value)
    value["name"] = "Changed"
    app_module.store.save_collector(value)
    response = command(
        client, "POST", f"/api/v1/collectors/{value['id']}/lifecycle", {"action": "delete", "planDigest": plan["planDigest"]}
    )
    assert response.status_code == 409
    from extrio.collector_lifecycle import lifecycle_command, lifecycle_plan

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(app_module.store, "_append_audit_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        lifecycle_command(
            app_module.store,
            value["id"],
            {"action": "delete", "planDigest": lifecycle_plan(app_module.store, value["id"])["planDigest"]},
            "audit-failure-key",
            {"tenantId": "default", "actorId": "test", "requestId": "test"},
        )
    assert app_module.store.get_collector(value["id"])["schedule"] is not None


def test_stale_writers_cannot_unarchive_or_resurrect_source(client):
    value = source()
    assert manage(client, value, "archive").status_code == 200
    value["name"] = "Stale edit"
    with pytest.raises(ValueError, match="COLLECTOR_CONFLICT"):
        app_module.store.save_collector(value)
    assert manage(client, value, "delete", "empty-archived-delete").status_code == 200
    with pytest.raises(ValueError, match="COLLECTOR_NOT_FOUND"):
        app_module.store.save_collector(value)


def test_archive_rejects_definition_policy_migration_and_execution(client):
    value = source()
    assert manage(client, value, "archive").status_code == 200
    for path, method, body in (
        ("", "PATCH", {k: value[k] for k in ("name", "intent", "sourceUrl", "managementRevision")}),
        ("/explorations", "POST", {}),
        ("/repairs", "POST", {}),
        ("/publish", "POST", {"reviewDecisions": {}}),
        ("/runs", "POST", None),
        ("/schedule", "PUT", {"enabled": True, "cronExpression": "0 8 * * *", "timezone": "Asia/Shanghai", "overlapPolicy": "forbid"}),
        (
            "/collection-policy",
            "POST",
            {
                k: value["collectionPolicy"][k]
                for k in ("mode", "initialWindowDays", "lookbackDays", "consecutiveOlderPages", "maxPages", "maxItems", "timezone")
            },
        ),
    ):
        response = command(client, method, f"/api/v1/collectors/{value['id']}" + path, body, "archived-entry-key-" + path)
        assert response.status_code == 409, (path, response.json())
        assert response.json()["code"] == "COLLECTOR_ARCHIVED", (path, response.json())


def test_archive_and_enqueue_serialize_on_the_source(client):
    from concurrent.futures import ThreadPoolExecutor

    from extrio.collector_lifecycle import lifecycle_command, lifecycle_plan

    store = app_module.store
    value = source()
    body = {"action": "archive", "planDigest": lifecycle_plan(store, value["id"])["planDigest"]}

    def archive():
        try:
            lifecycle_command(
                store,
                value["id"],
                body,
                "race-archive-command",
                {"tenantId": app_module.settings.tenant_id, "actorId": "test", "requestId": "test"},
            )
            return "archived"
        except ValueError:
            return "archive-blocked"

    def enqueue():
        try:
            store.create_async_command(
                kind="explore",
                collector_id=value["id"],
                resource_type="collector",
                resource_id=value["id"],
                job_payload={"collectorId": value["id"]},
            )
            return "enqueued"
        except ValueError:
            return "enqueue-blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(archive), pool.submit(enqueue)
        result = (a.result(), b.result())
    assert result in {("archived", "enqueue-blocked"), ("archive-blocked", "enqueued")}


def test_claimed_schedule_cannot_dispatch_after_archive(client):
    from datetime import UTC, datetime, timedelta

    from extrio.store import DEFAULT_COLLECTOR_SCHEDULE

    value = source()
    app_module.store.save_schedule(value["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    occurrences = app_module.store.claim_due_schedules(datetime.now(UTC) + timedelta(days=2))
    assert len(occurrences) == 1
    assert manage(client, value, "archive").status_code == 200
    with pytest.raises(app_module.RunStartError) as raised:
        app_module.create_run_operation(value["id"])
    assert raised.value.code == "COLLECTOR_ARCHIVED"
    assert app_module.store.claim_due_schedules(datetime.now(UTC) + timedelta(days=3)) == []


def test_processing_jobs_block_and_completed_history_is_preserved(client):
    value = source()
    operation = app_module.store.create_async_command(
        kind="explore",
        collector_id=value["id"],
        resource_type="collector",
        resource_id=value["id"],
        job_payload={"collectorId": value["id"]},
    )
    job = app_module.store.claim_job(60)
    assert manage(client, value, "archive").status_code == 409
    app_module.store.update_operation(operation["id"], status="succeeded")
    assert manage(client, value, "archive").status_code == 409
    app_module.store.finish_job(job["id"])
    assert manage(client, value, "archive").status_code == 200
    assert manage(client, value, "delete", "history-delete-key").status_code == 200
    assert app_module.store.get_operation(operation["id"])["status"] == "succeeded"


def test_core_enqueue_cannot_overlap_a_durable_task(client):
    value = source()
    args = dict(
        kind="explore",
        collector_id=value["id"],
        resource_type="collector",
        resource_id=value["id"],
        job_payload={"collectorId": value["id"]},
        activate_collector=False,
    )
    app_module.store.create_async_command(**args)
    with pytest.raises(ValueError, match="TASK_ALREADY_ACTIVE"):
        app_module.store.create_async_command(**args)


@pytest.mark.parametrize("role", ["engineer", "reviewer", "viewer"])
def test_management_role_boundaries(user_store, role):
    make_user(user_store, role, role)
    client = login_client(role, PASSWORDS[role])
    value = source()
    response = manage(client, value, "archive")
    assert response.status_code == (200 if role == "engineer" else 403)


# ruff: noqa: F811
# Pytest injects the imported fixtures by parameter name.
