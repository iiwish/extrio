from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from test_collection_versions import client as client
from test_collection_versions import command
from test_collector_lifecycle import manage, preview, source
from test_collector_reassignment import published
from test_worker import accepted_item

import extrio.app as app_module
from extrio.collector_lifecycle import lifecycle_command, lifecycle_plan
from extrio.store import DEFAULT_COLLECTOR_SCHEDULE


def test_delete_published_source_preserves_history_and_releases_identity(client):
    store = app_module.store
    value = published(client)
    run = {"id": "deleted_source_run", "collectorId": value["id"], "collectorName": value["name"],
           "status": "succeeded", "ruleVersion": value["activeRuleVersion"]}
    store.save_run(run)
    item = {**accepted_item(run_id=run["id"]), "collectorId": value["id"]}
    store.save_items(run["id"], [item])
    sink = store.create_sink(value["id"], cipher=app_module.credential_cipher, url="https://example.com/retained-webhook")
    delivery = store.enqueue_delivery(collector_id=value["id"], sink_id=sink["id"], item_event_id=item["id"])
    store.save_schedule(value["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    before_rule = store.get_rule_version(value["activeRuleVersion"])
    with store.connect() as connection:
        before_run = connection.execute("SELECT data FROM runs WHERE id=?", (run["id"],)).fetchone()["data"]
        before_item = connection.execute("SELECT data FROM items WHERE id=?", (item["id"],)).fetchone()["data"]
    plan = preview(client, value)
    assert plan["deleteBlockers"] == []
    assert plan["historyCounts"]["rules"] == 1
    assert plan["historyCounts"]["runs"] == plan["historyCounts"]["items"] == 1
    assert plan["historyCounts"]["sinks"] == plan["historyCounts"]["deliveries"] == 1
    assert plan["scheduleEnabled"] is True
    assert manage(client, value, "delete").status_code == 200
    assert store.get_collector(value["id"]) is None
    assert client.get(f"/api/v1/collectors/{value['id']}").status_code == 404
    assert store.get_collector(value["id"], include_deleted=True)["deletedAt"]
    assert store.list_collectors() == []
    assert store.get_collection(value["collectionId"])["sourceCount"] == 0
    assert store.list_collections()[0]["sourceCount"] == 0
    assert client.get("/api/v1/overview").json()["collectors"] == {"total": 0, "published": 0}
    assert store.count_collectors_by_status() == {}
    assert store.claim_due_schedules(datetime.now(UTC) + timedelta(days=3)) == []
    assert store.get_rule_version(value["activeRuleVersion"]) == before_rule
    assert store.get_sink(sink["id"]) == sink
    assert store.get_delivery(delivery["id"]) == delivery
    assert client.get(f"/api/v1/collectors/{value['id']}/deliveries").status_code == 200
    assert client.get(f"/api/v1/collectors/{value['id']}/sinks").status_code == 200
    with pytest.raises(ValueError, match="COLLECTOR_NOT_FOUND"):
        store.create_sink(value["id"], cipher=app_module.credential_cipher, url="https://example.com/new-webhook")
    with pytest.raises(ValueError, match="COLLECTOR_NOT_FOUND"):
        store.update_sink(sink["id"], enabled=False)
    with pytest.raises(ValueError, match="COLLECTOR_NOT_FOUND"):
        store.delete_sink(sink["id"])
    assert store.get_run(run["id"])["collectorDeleted"] is True
    assert store.get_item(item["id"])["collectorDeleted"] is True
    assert store.list_runs()[0]["collectorDeleted"] is True
    for view in ("entities", "observations"):
        assert store.list_items_cursor(view=view)["items"][0]["collectorDeleted"] is True
    assert store.get_item(item["id"])["collectionAttribution"]["collectionId"] == value["collectionId"]
    with store.connect() as connection:
        assert connection.execute("SELECT data FROM runs WHERE id=?", (run["id"],)).fetchone()["data"] == before_run
        assert connection.execute("SELECT data FROM items WHERE id=?", (item["id"],)).fetchone()["data"] == before_item
    assert client.get(f"/api/v1/collectors/{value['id']}/evidence-bundle").status_code == 200
    replacement = store.create_collector(value["name"], value["intent"], value["sourceUrl"], value["sourceHost"])
    assert replacement["id"] != value["id"]
    assert replacement["activeRuleVersion"] is None
    assert replacement.get("candidate") is None
    assert replacement["schedule"]["enabled"] is False
    assert store.latest_accepted_items(replacement["id"], {item["entityKey"]}) == []
    assert store.list_sinks_for_collector(replacement["id"]) == []
    assert len(store.list_collectors()) == 1
    store.initialize()
    assert store.get_collector(value["id"]) is None
    assert len(store.list_collectors()) == 1


def test_completed_ai_history_does_not_block_delete(client):
    store = app_module.store
    value = source()
    operation = store.create_async_command(kind="explore", collector_id=value["id"], resource_type="collector",
                                           resource_id=value["id"], job_payload={"collectorId": value["id"]})
    job = store.claim_job(60)
    ai = {"id": "deleted_source_ai", "collectorId": value["id"], "status": "failed"}
    store.save_ai_run(ai, value["id"], operation["id"])
    store.update_operation(operation["id"], status="failed")
    store.finish_job(job["id"])
    plan = preview(client, value)
    assert plan["deleteBlockers"] == []
    assert plan["historyCounts"]["operations"] == plan["historyCounts"]["ai_runs"] == 1
    assert manage(client, value, "delete").status_code == 200
    assert store.get_operation(operation["id"])["collectorDeleted"] is True
    assert store.get_ai_run(ai["id"])["collectorDeleted"] is True
    assert store.list_ai_runs(value["id"])[0]["collectorDeleted"] is True


def test_deleted_source_cannot_restore_edit_or_execute(client):
    value = source()
    old_plan = preview(client, value)
    assert manage(client, value, "delete").status_code == 200
    base = f"/api/v1/collectors/{value['id']}"
    for action in ("restore", "archive", "delete"):
        response = command(client, "POST", base + "/lifecycle",
                           {"action": action, "planDigest": old_plan["planDigest"]}, "deleted-source-action-" + action)
        assert response.status_code == 404
    with pytest.raises(ValueError, match="COLLECTOR_NOT_FOUND"):
        app_module.store.save_collector(value)
    with pytest.raises(ValueError, match="COLLECTOR_NOT_FOUND"):
        app_module.store.create_async_command(kind="explore", collector_id=value["id"], resource_type="collector",
                                             resource_id=value["id"], job_payload={})
    for path in ("/explorations", "/repairs", "/runs", "/publish"):
        response = command(client, "POST", base + path, {"reviewDecisions": {}} if path == "/publish" else {}, "deleted-entry-" + path)
        assert response.status_code == 404, (path, response.json())


def test_delete_and_enqueue_serialize_without_history_loss(client):
    store = app_module.store
    value = source()
    body = {"action": "delete", "planDigest": lifecycle_plan(store, value["id"])["planDigest"]}
    def remove():
        try:
            lifecycle_command(store, value["id"], body, "race-delete", {"tenantId": "default", "actorId": "test", "requestId": "test"})
            return "deleted"
        except ValueError:
            return "blocked"
    def enqueue():
        try:
            store.create_async_command(kind="explore", collector_id=value["id"], resource_type="collector",
                                       resource_id=value["id"], job_payload={})
            return "enqueued"
        except ValueError:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion, execution = pool.submit(remove), pool.submit(enqueue)
        assert (deletion.result(), execution.result()) in {("deleted", "blocked"), ("blocked", "enqueued")}


def test_empty_deleted_source_does_not_resurrect_requirement_on_initialize(client):
    store = app_module.store
    requirement = store.create_collection("Disposable", "Collect")
    value = store.create_collector("Empty", "Collect", "https://example.com/disposable", "example.com",
                                   collection_id=requirement["id"], collection_name=requirement["name"])
    assert manage(client, value, "delete").status_code == 200
    store.delete_collection(requirement["id"], requirement["revision"])
    store.initialize()
    assert store.get_collection(requirement["id"]) is None
    assert store.get_collector(value["id"]) is None


def test_nonterminal_ai_or_persisted_migration_blocks_delete(client):
    store = app_module.store
    value = source()
    operation = store.create_async_command(kind="explore", collector_id=value["id"], resource_type="collector",
                                           resource_id=value["id"], job_payload={})
    job = store.claim_job(60)
    store.update_operation(operation["id"], status="failed")
    store.finish_job(job["id"])
    ai = {"id": "unfinished_source_ai", "collectorId": value["id"], "status": "running"}
    store.save_ai_run(ai, value["id"], operation["id"])
    assert "TASK_ALREADY_ACTIVE" in preview(client, value)["deleteBlockers"]
    assert manage(client, value, "delete").status_code == 409
    store.save_ai_run({**ai, "status": "failed"}, value["id"], operation["id"])
    with store.transaction() as connection:
        connection.execute("INSERT INTO collection_migrations(collector_id, data) VALUES(?, ?)",
                           (value["id"], store.dialect.json_param({"status": "awaiting_compile"})))
    assert "MIGRATION_ALREADY_ACTIVE" in preview(client, value)["deleteBlockers"]
    assert manage(client, value, "delete", "delete-with-pending-migration").status_code == 409


def test_finished_history_changes_require_a_fresh_delete_preview(client):
    store = app_module.store
    value = source()
    old = preview(client, value)
    operation = store.create_async_command(kind="explore", collector_id=value["id"], resource_type="collector",
                                           resource_id=value["id"], job_payload={}, activate_collector=False)
    job = store.claim_job(60)
    store.update_operation(operation["id"], status="failed")
    store.finish_job(job["id"])
    result = command(client, "POST", f"/api/v1/collectors/{value['id']}/lifecycle",
                     {"action": "delete", "planDigest": old["planDigest"]}, "old-history-preview")
    assert result.status_code == 409
    assert result.json()["code"] == "COLLECTOR_CONFLICT"
    assert manage(client, value, "delete", "fresh-history-preview").status_code == 200


def test_history_delete_audit_failure_rolls_back_schedule_and_tombstone(client, monkeypatch):
    store = app_module.store
    value = published(client)
    store.save_schedule(value["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    before = store.get_collector(value["id"])
    body = {"action": "delete", "planDigest": preview(client, value)["planDigest"]}
    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(store, "_append_audit_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        lifecycle_command(store, value["id"], body, "delete-audit-failure", {
            "tenantId": "default", "actorId": "test", "requestId": "test"})
    assert store.get_collector(value["id"]) == before
    assert store.source_exists(value["sourceUrl"])
    assert store.get_rule_version(value["activeRuleVersion"]) is not None
    with store.connect() as connection:
        assert connection.execute("SELECT 1 FROM deleted_collectors WHERE id=?", (value["id"],)).fetchone() is None
