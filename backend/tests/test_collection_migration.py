from test_collection_versions import client  # noqa: F401, F811 - pytest fixture registration
from test_collection_versions import command as request_command

import extrio.app as app_module


def command(client, method, path, body=None, key="default-migration-command"):
    return request_command(client, method, path, body, "g2-test-command-" + key)


def setup_migration(client):
    col = command(client, "POST", "/api/v1/collections", {"name": "Migration", "intent": "Test"}, "migration-col").json()
    source = command(
        client,
        "POST",
        "/api/v1/collectors/batch",
        {
            "collectionId": col["id"],
            "collectionName": col["name"],
            "intent": col["intent"],
            "sources": [{"entryUrl": "https://example.com/migration", "mode": "exact"}],
        },
        "migration-source",
    ).json()["results"][0]["collector"]
    fields = [
        {"key": "title", "label": "Title", "description": "", "type": "string", "required": True, "identity": True, "fingerprint": True}
    ]
    command(
        client,
        "PATCH",
        f"/api/v1/collections/{col['id']}",
        {"revision": col["revision"], "fieldDraft": {"fields": fields}},
        "migration-draft",
    )
    version = command(
        client, "POST", f"/api/v1/collections/{col['id']}/publish-version", {"revision": col["revision"] + 1}, "migration-version"
    ).json()
    return col, source, version


def get_plan(client, source, version):
    response = client.get(f"/api/v1/collectors/{source['id']}/collection-migration", params={"targetVersionId": version["id"]})
    assert response.status_code == 200
    return response.json()


def start(client, source, version, plan, key="migration-start", **extra):
    return command(
        client,
        "POST",
        f"/api/v1/collectors/{source['id']}/collection-migration",
        {
            "targetVersionId": version["id"],
            "planDigest": plan["planDigest"],
            "confirmedChanges": [change["key"] for change in plan["changes"]],
            **extra,
        },
        key,
    )


def test_migration_requires_review_and_keeps_old_binding_until_rule_publish(client):
    col, source, version = setup_migration(client)
    plan = get_plan(client, source, version)
    assert plan["targetVersionId"] == version["id"]
    assert plan["requiresRecompile"] is True
    assert plan["changes"]
    unreviewed = start(client, source, version, plan, "unreviewed", confirmedChanges=[])
    assert unreviewed.status_code == 409
    response = start(client, source, version, plan)
    assert response.status_code == 200
    migrated = response.json()
    assert migrated["collectionVersion"] == source["collectionVersion"]
    assert migrated["pendingCollectionVersion"] == version["id"]
    assert migrated["collectionMigration"]["status"] == "awaiting_compile"
    assert migrated["activeRuleVersion"] == source["activeRuleVersion"]
    contracts = client.get(f"/api/v1/collections/{col['id']}").json()["sourceContracts"]
    assert contracts[0]["isAligned"] is False
    replay = start(client, source, version, plan)
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert command(client, "POST", f"/api/v1/collectors/{source['id']}/runs", key="migration-run").status_code == 409
    cancel = command(
        client,
        "POST",
        f"/api/v1/collectors/{source['id']}/collection-migration/cancel",
        {"targetVersionId": version["id"]},
        "migration-cancel",
    )
    assert cancel.status_code == 200
    assert cancel.json()["pendingCollectionVersion"] is None
    assert cancel.json()["collectionVersion"] == source["collectionVersion"]
    assert app_module.store.verify_audit_chain(app_module.settings.tenant_id)


def test_stale_plan_and_active_run_cannot_migrate(client):
    _, source, version = setup_migration(client)
    plan = get_plan(client, source, version)
    altered = app_module.store.get_collector(source["id"])
    altered["intent"] = "Changed by another operator"
    app_module.store.save_collector(altered)
    assert start(client, source, version, plan).status_code == 409
    app_module.store.save_run({"id": "run_active", "collectorId": source["id"], "status": "running"})
    active_plan = get_plan(client, source, version)
    assert "RUN_ALREADY_ACTIVE" in active_plan["blockers"]
    assert start(client, source, version, active_plan, "active-run").status_code == 409


def test_migration_cannot_use_version_from_other_requirement(client):
    _, source, version = setup_migration(client)
    other = app_module.store.create_collector("Other", "Other", "https://example.com/other", "example.com")
    response = client.get(f"/api/v1/collectors/{other['id']}/collection-migration", params={"targetVersionId": version["id"]})
    assert response.status_code == 404


def test_publish_switches_binding_only_when_candidate_matches_reviewed_target(client, tmp_path):
    from extrio.harvest import build_candidate_from_plan
    from extrio.model_gateway import normalize_discovery_plan, normalize_rule_plan

    _, source, version = setup_migration(client)
    plan = get_plan(client, source, version)
    assert start(client, source, version, plan).status_code == 200
    current = app_module.store.get_collector(source["id"])
    context = app_module.store.collector_compilation_context(current)
    raw = {
        "mode": "single",
        "transport": "http",
        "list": {
            "responseType": "html",
            "itemsSelector": "css:body",
            "pagination": {"type": "none"},
            "fields": {"title": {"selector": "css:h1::text", "required": True}},
        },
        "rationale": "test",
    }
    candidate = build_candidate_from_plan(
        context, app_module.contracts, normalize_rule_plan(raw, normalize_discovery_plan(raw)), "<h1>A</h1>", []
    )
    current.update(status="ready_review", candidate=candidate)
    app_module.store.save_collector(current)
    import copy

    for index, key in enumerate(("normalizedItemSchema", "identityFields", "fingerprintFields", "outputContractDigest")):
        tampered = copy.deepcopy(current)
        tampered["candidate"]["gatherSpec"]["contract"][key] = (
            [] if key.endswith("Fields") else {} if key == "normalizedItemSchema" else "sha256:" + "0" * 64
        )
        app_module.store.save_collector(tampered)
        rejected = command(
            client,
            "POST",
            f"/api/v1/collectors/{source['id']}/publish",
            {"reviewDecisions": {"title": "approved"}},
            f"tampered-publish-{index}",
        )
        assert rejected.status_code in {409, 422}, rejected.text
        assert app_module.store.get_collector(source["id"])["collectionVersion"] == source["collectionVersion"]
    app_module.store.save_collector(current)
    published = command(
        client, "POST", f"/api/v1/collectors/{source['id']}/publish", {"reviewDecisions": {"title": "approved"}}, "publish-migration-target"
    )
    assert published.status_code == 200, published.text
    assert published.json()["collectionVersion"] == version["id"]
    assert published.json()["pendingCollectionVersion"] is None
    assert published.json()["collectionMigration"] is None
    rule = app_module.store.get_rule_version(published.json()["activeRuleVersion"])
    assert rule["gatherSpec"]["collectionVersionRef"]["collectionVersionId"] == version["id"]

    # The real runtime and Worker must preserve the reviewed contract after draft edits.
    import asyncio

    from extrio.runtime import CrawleeRuntime
    from extrio.worker import Worker

    collection = app_module.store.get_collection(version["collectionId"])
    app_module.store.change_collection(collection["id"], collection["revision"], {"fieldDraft": {"fields": []}})
    accepted = command(client, "POST", f"/api/v1/collectors/{source['id']}/runs", key="run-migrated-contract")
    assert accepted.status_code == 202, accepted.text

    class FixtureRuntime(CrawleeRuntime):
        async def _fetch_many(self, urls, transport="http", browser_policy=None):
            assert urls == [source["sourceUrl"]]
            return {source["sourceUrl"]: "<h1>A</h1>"}

    worker = Worker.__new__(Worker)
    worker.store = app_module.store
    worker.contracts = app_module.contracts
    worker.runtime = FixtureRuntime(tmp_path / "runtime-artifacts")
    job = app_module.store.claim_job(60)
    assert job["kind"] == "run"
    asyncio.run(worker.process(job))
    app_module.store.finish_job(job["id"])
    run = app_module.store.get_run(accepted.json()["resourceId"])
    assert run["status"] == "succeeded"
    assert run["items"][0]["extractedData"] == {"title": "A"}
    assert run["items"][0]["lineage"]["collectionVersion"] == version["id"]
    assert run["items"][0]["lineage"]["ruleVersion"] == rule["id"]
    assert app_module.store.verify_audit_chain(app_module.settings.tenant_id)


# ruff: noqa: F811
# Pytest injects the imported fixtures by parameter name.
