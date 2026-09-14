import copy

import pytest
from test_api import ready_review_collector
from test_collection_versions import client, command  # noqa: F401, F811 - pytest fixture registration
from test_collector_lifecycle import source

import extrio.app as app_module
from extrio.store import DEFAULT_COLLECTOR_SCHEDULE


def target(client, key="target"):
    result = command(client, "POST", "/api/v1/collections", {"name": key, "intent": "Target goal"}, "create-target-" + key)
    assert result.status_code == 201
    return result.json()


def plan(client, value, destination):
    result = client.get(f"/api/v1/collectors/{value['id']}/reassignment", params={"targetCollectionId": destination["id"]})
    assert result.status_code == 200, result.json()
    return result.json()


def move(client, value, destination, preview=None, key="reassign-command-key"):
    preview = preview or plan(client, value, destination)
    return command(
        client,
        "POST",
        f"/api/v1/collectors/{value['id']}/reassignment",
        {
            "targetCollectionId": destination["id"],
            "planDigest": preview["planDigest"],
            "confirmedChanges": [change["key"] for change in preview["changes"]],
        },
        key,
    )


def published(client):
    value = ready_review_collector(app_module.store)
    result = command(
        client,
        "POST",
        f"/api/v1/collectors/{value['id']}/publish",
        {"reviewDecisions": {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}},
        "publish-source-key",
    )
    assert result.status_code == 200, result.json()
    return result.json()


def test_empty_reassignment_and_replay(client):
    value, destination = source(), target(client)
    preview = plan(client, value, destination)
    assert preview["blockers"] == []
    assert preview["requiresRecompile"] is False
    result = move(client, value, destination, preview)
    assert result.status_code == 200
    assert result.json()["collectionId"] == destination["id"]
    assert result.json()["intent"] == destination["intent"]
    assert result.json()["schedule"]["enabled"] is False
    assert move(client, value, destination, preview).headers["Idempotency-Replayed"] == "true"
    assert app_module.store.get_collection(value["collectionId"])["sourceCount"] == 0


def test_target_revision_archive_and_self_are_rejected(client):
    value, destination = source(), target(client)
    preview = plan(client, value, destination)
    assert (
        command(client, "PATCH", f"/api/v1/collections/{destination['id']}", {"revision": 1, "name": "Changed target"}).status_code == 200
    )
    assert move(client, value, destination, preview).json()["code"] == "COLLECTOR_CONFLICT"
    command(client, "PATCH", f"/api/v1/collections/{destination['id']}", {"revision": 2, "status": "archived"}, "archive-target-key")
    assert "COLLECTION_ARCHIVED" in plan(client, value, destination)["blockers"]
    assert move(client, value, destination).status_code == 409
    assert "COLLECTION_ALREADY_BOUND" in plan(client, value, {"id": value["collectionId"]})["blockers"]


def test_definition_change_disables_schedule_and_rejects_stale_edit(client):
    value = published(client)
    app_module.store.save_schedule(value["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    body = {
        "name": "Renamed",
        "intent": value["intent"],
        "sourceUrl": value["sourceUrl"],
        "managementRevision": value["managementRevision"],
    }
    renamed = command(client, "PATCH", f"/api/v1/collectors/{value['id']}", body, "definition-rename-key")
    assert renamed.status_code == 200
    assert renamed.json()["activeRuleVersion"] == value["activeRuleVersion"]
    assert renamed.json()["schedule"]["enabled"] is True
    changed = command(
        client,
        "PATCH",
        f"/api/v1/collectors/{value['id']}",
        {**body, "intent": "New intent", "managementRevision": renamed.json()["managementRevision"]},
        "definition-change-key",
    )
    assert changed.status_code == 200
    assert changed.json()["activeRuleVersion"] is None
    assert changed.json()["schedule"]["enabled"] is False
    assert changed.json()["candidate"] is None
    assert app_module.store.get_rule_version(value["activeRuleVersion"]) is not None
    assert (
        command(client, "PATCH", f"/api/v1/collectors/{value['id']}", body, "definition-stale-key").json()["code"] == "COLLECTOR_CONFLICT"
    )


def test_move_preserves_historical_rule_run_items_and_new_execution_is_blocked(client):
    from test_worker import accepted_item

    value, destination = published(client), target(client)
    store = app_module.store
    rule = copy.deepcopy(store.get_rule_version(value["activeRuleVersion"]))
    run = {
        "id": "run_old",
        "collectorId": value["id"],
        "collectorName": value["name"],
        "status": "succeeded",
        "ruleVersion": value["activeRuleVersion"],
    }
    store.save_run(run)
    item = {**accepted_item(run_id=run["id"]), "collectorId": value["id"]}
    store.save_items(run["id"], [item])
    with store.connect() as connection:
        old_run = store._decode(connection.execute("SELECT data FROM runs WHERE id=?", (run["id"],)).fetchone())
        old_item = store._decode(connection.execute("SELECT data FROM items WHERE id=?", (item["id"],)).fetchone())
    preview = plan(client, value, destination)
    assert preview["requiresRecompile"] is True
    result = move(client, value, destination, preview)
    assert result.status_code == 200, result.json()
    assert result.json()["activeRuleVersion"] is None
    assert result.json()["status"] == "draft"
    assert store.get_rule_version(value["activeRuleVersion"]) == rule
    assert store.get_run(run["id"])["collectionAttribution"]["collectionId"] == value["collectionId"]
    assert store.get_item(item["id"])["collectionAttribution"]["collectionId"] == value["collectionId"]
    assert store.list_items_cursor()["items"][0]["collectionAttribution"]["collectionId"] == value["collectionId"]
    with store.connect() as connection:
        assert store._decode(connection.execute("SELECT data FROM runs WHERE id=?", (run["id"],)).fetchone()) == old_run
        assert store._decode(connection.execute("SELECT data FROM items WHERE id=?", (item["id"],)).fetchone()) == old_item
    assert store.latest_accepted_items(value["id"], {item["entityKey"]}) == []
    assert (
        command(client, "POST", f"/api/v1/collectors/{value['id']}/runs", None, "run-after-reassign").json()["code"] == "RULE_NOT_PUBLISHED"
    )


def test_unresolvable_legacy_run_blocks_move_without_guessing(client):
    value, destination = source(), target(client)
    with app_module.store.transaction() as connection:
        connection.execute(
            "INSERT INTO runs(id, collector_id, data, created_at, updated_at) VALUES(?, ?, ?, ?, ?)",
            (
                "run_legacy_unknown",
                value["id"],
                app_module.store.dialect.json_param(
                    {"id": "run_legacy_unknown", "collectorId": value["id"], "status": "succeeded", "ruleVersion": "missing_rule"}
                ),
                "2026-09-01T00:00:00Z",
                "2026-09-01T00:00:00Z",
            ),
        )
    preview = plan(client, value, destination)
    assert "HISTORY_OWNERSHIP_UNRESOLVED" in preview["blockers"]
    assert {"type": "run", "id": "run_legacy_unknown"} in preview["unresolvedHistory"]
    assert move(client, value, destination, preview).status_code == 409
    assert app_module.store.get_collector(value["id"])["collectionId"] == value["collectionId"]


def test_stale_publish_cannot_reactivate_a_previous_definition(client):
    value = ready_review_collector(app_module.store)
    result = command(
        client,
        "PATCH",
        f"/api/v1/collectors/{value['id']}",
        {"name": value["name"], "intent": "Changed intent", "sourceUrl": value["sourceUrl"], "managementRevision": 0},
        "edit-before-publish",
    )
    assert result.status_code == 200
    with pytest.raises(ValueError, match="COLLECTOR_CONFLICT"):
        app_module.persist_published_rule(
            value,
            rule_version_id=app_module.next_rule_version_id(value["id"], 1),
            review_decisions={"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"},
            request_id="stale-publish",
            actor_id="test",
        )
    assert app_module.store.get_collector(value["id"])["activeRuleVersion"] is None


def test_same_entity_after_move_keeps_separate_requirement_history(client):
    from test_worker import accepted_item

    value, destination = source(), target(client)
    store = app_module.store
    for number in (1, 2):
        run_id = f"run_scope_{number}"
        store.save_run({"id": run_id, "collectorId": value["id"], "status": "failed"})
        store.save_items(run_id, [{**accepted_item(run_id=run_id), "collectorId": value["id"]}])
        if number == 1:
            assert move(client, value, destination).status_code == 200
    result = store.list_items_cursor(view="entities")
    assert result["total"] == 2
    assert {item["collectionAttribution"]["collectionId"] for item in result["items"]} == {value["collectionId"], destination["id"]}
    assert len(store.recent_run_statuses(value["id"], 3)) == 1


def test_reassignment_requires_field_review_and_republish_uses_new_rule_id(client):
    from extrio.harvest import build_candidate

    value, destination = published(client), target(client)
    preview = plan(client, value, destination)
    assert preview["changes"]
    bad = command(
        client,
        "POST",
        f"/api/v1/collectors/{value['id']}/reassignment",
        {"targetCollectionId": destination["id"], "planDigest": preview["planDigest"], "confirmedChanges": []},
    )
    assert bad.json()["code"] == "REASSIGNMENT_REVIEW_REQUIRED"
    changed = move(client, value, destination, preview).json()
    changed["candidate"] = build_candidate(
        changed,
        app_module.contracts,
        '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">A</a></li></ul>',
        [
            (
                "https://example.com/detail/1",
                '<h1 class="notice-title">A</h1><div class="meta"><span data-field="buyer">B</span>'
                '<time datetime="2026-08-31T00:00:00Z"></time></div>',
            )
        ],
    )
    changed["status"] = "ready_review"
    app_module.store.save_collector(changed)
    result = command(
        client,
        "POST",
        f"/api/v1/collectors/{value['id']}/publish",
        {"reviewDecisions": {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}},
        "republish-after-move",
    )
    assert result.status_code == 200, result.json()
    assert result.json()["activeRuleVersion"] != value["activeRuleVersion"]
    assert result.json()["candidate"]["gatherSpec"]["collectionVersionRef"]["collectionId"] == destination["id"]
    run = command(client, "POST", f"/api/v1/collectors/{value['id']}/runs", None, "run-new-requirement")
    assert run.status_code == 202, run.json()
    assert app_module.store.get_run(run.json()["resourceId"])["collectionAttribution"]["collectionId"] == destination["id"]


def test_ai_history_stays_with_original_requirement_across_multiple_moves(client):
    value, destination = source(), target(client)
    store = app_module.store
    operation = store.create_async_command(
        kind="explore",
        collector_id=value["id"],
        resource_type="collector",
        resource_id=value["id"],
        job_payload={"aiRunId": "ai_history"},
        ai_run={"id": "ai_history", "collectorId": value["id"], "kind": "rule_generation"},
    )
    job = store.claim_job(60)
    store.update_operation(operation["id"], status="succeeded")
    store.update_ai_run("ai_history", status="succeeded")
    store.finish_job(job["id"])
    assert move(client, value, destination).status_code == 200
    other = target(client, "second")
    assert move(client, value, other, key="second-move-command").status_code == 200
    assert store.get_ai_run("ai_history")["collectionAttribution"]["collectionId"] == value["collectionId"]
    assert store.get_operation(operation["id"])["collectionAttribution"]["collectionId"] == value["collectionId"]
    for action in ("UPDATE source_history_ownership SET data=data", "DELETE FROM source_history_ownership"):
        with pytest.raises(Exception, match="immutable"):
            with store.transaction() as connection:
                connection.execute(action)


def test_queued_work_and_pending_migration_block_reassignment(client):
    value, destination = source(), target(client)
    value["pendingCollectionVersion"] = "colver_pending"
    app_module.store.save_collector(value)
    assert "MIGRATION_ALREADY_ACTIVE" in plan(client, value, destination)["blockers"]
    assert move(client, value, destination).status_code == 409
    value["pendingCollectionVersion"] = None
    app_module.store.save_collector(value)
    app_module.store.create_async_command(
        kind="explore",
        collector_id=value["id"],
        resource_type="collector",
        resource_id=value["id"],
        job_payload={},
        activate_collector=False,
    )
    assert "TASK_ALREADY_ACTIVE" in plan(client, value, destination)["blockers"]
    assert move(client, value, destination).status_code == 409


def test_reassignment_audit_failure_rolls_back_binding_and_schedule(client, monkeypatch):
    from extrio.collector_lifecycle import reassignment_command

    value, destination = source(), target(client)
    app_module.store.save_schedule(value["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    preview = plan(client, value, destination)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(app_module.store, "_append_audit_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        reassignment_command(
            app_module.store,
            value["id"],
            {
                "targetCollectionId": destination["id"],
                "planDigest": preview["planDigest"],
                "confirmedChanges": [change["key"] for change in preview["changes"]],
            },
            "rollback-move-key",
            {"tenantId": "test"},
        )
    current = app_module.store.get_collector(value["id"])
    assert current["collectionId"] == value["collectionId"]
    assert current["schedule"]["enabled"] is True


# ruff: noqa: F811
# Pytest injects the imported fixtures by parameter name.
