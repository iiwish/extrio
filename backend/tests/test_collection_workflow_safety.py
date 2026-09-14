from concurrent.futures import ThreadPoolExecutor

import pytest
from test_collection_migration import command, get_plan, setup_migration, start
from test_collection_versions import client  # noqa: F401, F811 - pytest fixture registration
from test_field_suggestions import FIELDS, enqueue, requirement
from test_users import PASSWORDS, login_client, make_user, user_store  # noqa: F401, F811 - pytest fixture registration

import extrio.app as app_module


@pytest.mark.parametrize("role", ["engineer", "reviewer", "viewer"])
def test_collection_workflow_role_boundaries(user_store, role):
    make_user(user_store, role, role)
    client = login_client(role, PASSWORDS[role])
    for path in (
        "/collections/missing/publish-version",
        "/collectors/missing/collection-migration",
        "/collectors/missing/collection-migration/cancel",
    ):
        response = command(client, "POST", "/api/v1" + path, {}, f"review-{path}")
        assert response.status_code == (403 if role != "reviewer" else 404 if path.endswith("publish-version") else 422)
    for path in (
        "/collections/missing/apply-template",
        "/collections/missing/field-suggestions",
        "/collections/missing/field-suggestions/missing/apply",
    ):
        response = command(client, "POST", "/api/v1" + path, {}, f"edit-{path}")
        assert response.status_code == (403 if role != "engineer" else 422)


def test_publication_is_atomic_with_audit_and_serializes_revision(client, monkeypatch):
    col = requirement(client)
    command(client, "PATCH", f"/api/v1/collections/{col['id']}", {"revision": 1, "fieldDraft": {"fields": FIELDS}}, "prepare-atomic")
    store = app_module.store
    audit = {"tenantId": app_module.settings.tenant_id, "actorId": "test", "requestId": "test"}
    original = store._append_audit_event

    def fail(*args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(store, "_append_audit_event", fail)
    with pytest.raises(RuntimeError, match="audit down"):
        store.publish_collection_version_command(col["id"], {"revision": 2}, "atomic-publish-failure", audit=audit)
    assert store.list_collection_versions(col["id"]) == []
    assert store.get_collection(col["id"])["revision"] == 2
    monkeypatch.setattr(store, "_append_audit_event", original)

    def publish(index):
        try:
            return store.publish_collection_version_command(col["id"], {"revision": 2}, f"concurrent-publish-{index}", audit=audit)[0]
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, range(2)))
    assert sorted(map(str, outcomes)) == ["201", "COLLECTION_CONFLICT"]
    assert len(store.list_collection_versions(col["id"])) == 1
    assert store.verify_audit_chain(app_module.settings.tenant_id)


def test_migration_cancel_restores_snapshot_and_rejects_active_compilation(client):
    _, source, version = setup_migration(client)
    saved = app_module.store.get_collector(source["id"])
    saved.update(candidate={"snapshot": "preserve"}, reviewDecisions={"title": "approved"}, previewItems=[{"title": "old"}])
    app_module.store.save_collector(saved)
    plan = get_plan(client, source, version)
    assert start(client, source, version, plan).status_code == 200
    app_module.store.create_async_command(
        kind="explore",
        collector_id=source["id"],
        resource_type="collector",
        resource_id=source["id"],
        job_payload={"collectorId": source["id"]},
        activate_collector=True,
    )
    response = command(
        client,
        "POST",
        f"/api/v1/collectors/{source['id']}/collection-migration/cancel",
        {"targetVersionId": version["id"]},
        "cancel-active",
    )
    assert response.status_code == 409
    current = app_module.store.get_collector(source["id"])
    current.update(
        activeOperationId=None, candidate={"new": "failed"}, collectionMigration={**current["collectionMigration"], "status": "failed"}
    )
    app_module.store.save_collector(current)
    response = command(
        client,
        "POST",
        f"/api/v1/collectors/{source['id']}/collection-migration/cancel",
        {"targetVersionId": version["id"]},
        "cancel-failed",
    )
    assert response.status_code == 200
    for key in ("candidate", "reviewDecisions", "previewItems", "status", "collectionVersion", "activeRuleVersion"):
        assert response.json()[key] == saved[key]


def test_suggestion_foreign_apply_and_historical_delete_are_rejected(client):
    from extrio.field_suggestions import claim_suggestion, finish_suggestion

    col = requirement(client)
    suggestion = enqueue(client, col)
    finish_suggestion(app_module.store, claim_suggestion(app_module.store), fields=FIELDS)
    other = command(client, "POST", "/api/v1/collections", {"name": "Other", "intent": "Other"}, "other-requirement").json()
    response = command(
        client,
        "POST",
        f"/api/v1/collections/{other['id']}/field-suggestions/{suggestion['id']}/apply",
        {"revision": 1, "selectedKeys": ["title"]},
        "foreign-apply",
    )
    assert response.status_code == 404
    assert command(client, "DELETE", f"/api/v1/collections/{col['id']}", {"revision": 1}, "history-delete").status_code == 409


def test_workflow_responses_match_openapi(client):
    from pathlib import Path

    import yaml
    from jsonschema import Draft202012Validator, FormatChecker

    document = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/contracts/openapi.yaml").read_text())

    def validate(name, value):
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": document["components"]}, format_checker=FormatChecker()
        )
        validator.validate(value)

    col, source, version = setup_migration(client)
    validate("CollectionDetail", client.get(f"/api/v1/collections/{col['id']}").json())
    validate("CollectionVersion", version)
    validate("CollectionVersionList", client.get(f"/api/v1/collections/{col['id']}/versions").json())
    validate("CollectionTemplateList", client.get("/api/v1/collection-templates").json())
    validate("CollectionMigrationPlan", get_plan(client, source, version))
    col = app_module.store.get_collection(col["id"])
    validate("FieldSuggestion", enqueue(client, col))
    validate("FieldSuggestionList", client.get(f"/api/v1/collections/{col['id']}/field-suggestions").json())


def test_cancel_does_not_restore_review_for_a_changed_source_definition(client):
    _, source, version = setup_migration(client)
    saved = app_module.store.get_collector(source["id"])
    saved.update(status="ready_review", candidate={"snapshot": "old-definition"}, reviewDecisions={"title": "approved"})
    app_module.store.save_collector(saved)
    assert start(client, source, version, get_plan(client, source, version)).status_code == 200
    current = app_module.store.get_collector(source["id"])
    current.update(intent="Revised during migration", candidate=None, reviewDecisions=None)
    app_module.store.save_collector(current)
    result = command(
        client,
        "POST",
        f"/api/v1/collectors/{source['id']}/collection-migration/cancel",
        {"targetVersionId": version["id"]},
        "cancel-edited-source",
    )
    assert result.status_code == 200
    assert result.json()["intent"] == current["intent"]
    assert result.json()["status"] == "draft"
    assert result.json()["candidate"] is None
    assert result.json()["reviewDecisions"] is None


# ruff: noqa: F811
# Pytest injects the imported fixtures by parameter name.
