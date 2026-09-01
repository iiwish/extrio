import copy
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.credentials import CredentialCipher
from extrio.harvest import build_candidate
from extrio.integrity import IntegrityError
from extrio.store import Store
from extrio.worker import Worker


def ready_review_collector(store: Store) -> dict:
    collector = store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
    list_html = '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">A</a></li></ul>'
    detail_html = (
        '<h1 class="notice-title">A</h1><div class="meta"><span data-field="buyer">B</span>'
        '<time datetime="2026-08-31T00:00:00Z"></time></div>'
    )
    collector.update(
        status="ready_review",
        candidate=build_candidate(
            collector,
            app_module.contracts,
            list_html,
            [("https://example.com/detail/1", detail_html)],
        ),
    )
    store.save_collector(collector)
    return collector


def test_create_explore_command_and_idempotent_replay(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            key = "create-collector-0001"
            body = {"name": "Source", "intent": "Collect", "sourceUrl": "https://example.com/list"}
            response = client.post("/api/v1/collectors", headers={"Idempotency-Key": key}, json=body)
            assert response.status_code == 201
            replay = client.post("/api/v1/collectors", headers={"Idempotency-Key": key}, json=body)
            assert replay.status_code == 201
            assert replay.headers["Idempotency-Replayed"] == "true"
            collector = response.json()

            accepted = client.post(
                f"/api/v1/collectors/{collector['id']}/explorations",
                headers={"Idempotency-Key": "explore-command-0001"},
            )
            assert accepted.status_code == 202
            operation = client.get(accepted.json()["statusUrl"])
            assert operation.json()["status"] == "queued"
            assert client.get(f"/api/v1/collectors/{collector['id']}").json()["status"] == "exploring"
    finally:
        app_module.store = original


def test_batch_collectors_share_collection_identity(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            response = client.post(
                "/api/v1/collectors/batch",
                headers={"Idempotency-Key": "batch-collection-context-0001"},
                json={
                    "collectionName": "全国公共资源交易标讯",
                    "intent": "采集公开招标公告与发布时间。",
                    "sourceUrls": [
                        "https://a.example.gov.cn/notices",
                        "https://b.example.gov.cn/notices",
                    ],
                },
            )

            assert response.status_code == 200
            result = response.json()
            created = [item["collector"] for item in result["results"] if item["collector"]]
            assert result["collectionId"].startswith("collection_")
            assert len(created) == 2
            assert {collector["collectionId"] for collector in created} == {result["collectionId"]}
            assert {collector["collectionName"] for collector in created} == {"全国公共资源交易标讯"}
            assert all(collector["name"].startswith(collector["sourceHost"]) for collector in created)

            reused = client.post(
                "/api/v1/collectors/batch",
                headers={"Idempotency-Key": "batch-existing-collection-0001"},
                json={
                    "collectionId": result["collectionId"],
                    "collectionName": "不会覆盖已有需求",
                    "intent": "不会覆盖已有采集意图",
                    "sourceUrls": ["https://c.example.gov.cn/notices"],
                },
            )

            assert reused.status_code == 200, reused.json()
            reused_result = reused.json()
            reused_collector = reused_result["results"][0]["collector"]
            assert reused_result["collectionId"] == result["collectionId"]
            assert reused_result["collectionName"] == "全国公共资源交易标讯"
            assert reused_collector["intent"] == "采集公开招标公告与发布时间。"
    finally:
        app_module.store = original


def test_model_setting_persists_only_a_secret_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    monkeypatch.setenv("EXTRIO_TEST_MODEL_KEY", "not-returned-by-api")
    try:
        with TestClient(app_module.app) as client:
            initial = client.get("/api/v1/settings/model")
            assert initial.status_code == 200
            assert "apiKey" not in initial.json()

            body = {
                "provider": "deepseek",
                "baseUrl": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "secretRef": "env:EXTRIO_TEST_MODEL_KEY",
            }
            response = client.put(
                "/api/v1/settings/model",
                headers={"Idempotency-Key": "model-setting-0001"},
                json=body,
            )
            assert response.status_code == 200
            assert response.json()["secretConfigured"] is True
            assert response.json()["provider"] == "deepseek"
            assert "not-returned-by-api" not in response.text
            assert client.get("/api/v1/settings/model").json()["model"] == "deepseek-chat"
    finally:
        app_module.store = original


def test_model_setting_rejects_plaintext_secret_and_http_endpoint(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            base = {
                "provider": "custom",
                "baseUrl": "https://models.example.com/v1",
                "model": "model-a",
                "secretRef": "plaintext-secret",
            }
            secret_response = client.put(
                "/api/v1/settings/model",
                headers={"Idempotency-Key": "model-setting-invalid-0001"},
                json=base,
            )
            assert secret_response.status_code == 422
            assert secret_response.json()["pointer"] == "/secretRef"

            http_response = client.put(
                "/api/v1/settings/model",
                headers={"Idempotency-Key": "model-setting-invalid-0002"},
                json={**base, "secretRef": "env:EXTRIO_MODEL_API_KEY", "baseUrl": "http://models.example.com/v1"},
            )
            assert http_response.status_code == 422
            assert http_response.json()["pointer"] == "/baseUrl"
    finally:
        app_module.store = original


def test_model_configuration_encrypts_provider_keys_and_supports_default_switching(tmp_path: Path) -> None:
    original = app_module.store
    original_cipher = app_module.credential_cipher
    app_module.store = Store(tmp_path / "api.db")
    app_module.credential_cipher = CredentialCipher(tmp_path / "credential.key")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            body = {
                "providers": [
                    {
                        "id": "provider_openai",
                        "name": "OpenAI",
                        "provider": "openai",
                        "baseUrl": "https://api.openai.com/v1",
                        "apiKey": "openai-not-returned-by-api",
                        "enabled": True,
                    },
                    {
                        "id": "provider_deepseek",
                        "name": "DeepSeek",
                        "provider": "deepseek",
                        "baseUrl": "https://api.deepseek.com/v1",
                        "apiKey": "deepseek-not-returned-by-api",
                        "enabled": True,
                    },
                ],
                "models": [
                    {"id": "model_gpt", "providerId": "provider_openai", "modelId": "gpt-4.1-mini", "enabled": True},
                    {"id": "model_deepseek", "providerId": "provider_deepseek", "modelId": "deepseek-chat", "enabled": True},
                ],
                "defaultModelId": "model_deepseek",
            }
            response = client.put(
                "/api/v1/settings/models",
                headers={"Idempotency-Key": "model-configuration-0001"},
                json=body,
            )
            assert response.status_code == 200
            result = response.json()
            assert len(result["providers"]) == 2
            assert result["defaultModelId"] == "model_deepseek"
            assert next(model for model in result["models"] if model["id"] == "model_deepseek")["isDefault"] is True
            assert next(provider for provider in result["providers"] if provider["id"] == "provider_openai")["credentialConfigured"] is True
            assert "apiKey" not in response.text
            assert "not-returned-by-api" not in response.text
            stored_credentials = app_module.store.get_platform_setting("model-provider-credentials")
            assert "not-returned-by-api" not in str(stored_credentials)
            decrypted = app_module.credential_cipher.decrypt(stored_credentials["credentials"]["provider_openai"])
            assert decrypted == "openai-not-returned-by-api"

            edit = {
                **body,
                "providers": [{key: value for key, value in provider.items() if key != "apiKey"} for provider in body["providers"]],
            }
            edited = client.put(
                "/api/v1/settings/models",
                headers={"Idempotency-Key": "model-configuration-0002"},
                json=edit,
            )
            assert edited.status_code == 200
            assert all(provider["credentialConfigured"] for provider in edited.json()["providers"])
    finally:
        app_module.store = original
        app_module.credential_cipher = original_cipher


def test_platform_error_shape_for_missing_idempotency(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            response = client.post("/api/v1/collectors", json={})
            assert response.status_code == 400
            assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
            assert response.json()["requestId"] == response.headers["X-Request-ID"]
    finally:
        app_module.store = original


def test_collection_policy_endpoint_creates_immutable_version_and_replays(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
            body = {
                "mode": "rolling_incremental",
                "initialWindowDays": 90,
                "lookbackDays": 7,
                "consecutiveOlderPages": 3,
                "maxPages": 40,
                "maxItems": 800,
                "timezone": "Asia/Shanghai",
            }
            response = client.post(
                f"/api/v1/collectors/{collector['id']}/collection-policy",
                headers={"Idempotency-Key": "collection-policy-0001"},
                json=body,
            )
            assert response.status_code == 200
            updated = response.json()
            assert updated["collectionPolicy"]["version"] == 2
            assert updated["collectionPolicy"]["initialWindowDays"] == 90
            assert updated["activeCollectionPolicyId"] == updated["collectionPolicy"]["id"]
            assert updated["checkpoint"] is None

            replayed = client.post(
                f"/api/v1/collectors/{collector['id']}/collection-policy",
                headers={"Idempotency-Key": "collection-policy-0001"},
                json=body,
            )
            assert replayed.status_code == 200
            assert replayed.headers["Idempotency-Replayed"] == "true"
            assert replayed.json()["collectionPolicy"]["version"] == 2
    finally:
        app_module.store = original


def test_schedule_endpoint_updates_revision_and_next_run(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
            response = client.put(
                f"/api/v1/collectors/{collector['id']}/schedule",
                headers={"Idempotency-Key": "collector-schedule-0001"},
                json={
                    "enabled": True,
                    "cronExpression": "30 7 * * 1-5",
                    "timezone": "Asia/Shanghai",
                    "overlapPolicy": "forbid",
                },
            )
            assert response.status_code == 200
            schedule = response.json()["schedule"]
            assert schedule["enabled"] is True
            assert schedule["revision"] == 2
            assert schedule["cronExpression"] == "30 7 * * 1-5"
            assert schedule["nextRunAt"] is not None
    finally:
        app_module.store = original


def test_collector_definition_edit_preserves_name_only_and_invalidates_rule_inputs(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = ready_review_collector(app_module.store)
            decisions = {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}
            published = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "publish-before-definition-edit"},
                json={"reviewDecisions": decisions},
            ).json()

            renamed = client.patch(
                f"/api/v1/collectors/{collector['id']}",
                headers={"Idempotency-Key": "rename-collector-0001"},
                json={"name": "Renamed", "intent": published["intent"], "sourceUrl": published["sourceUrl"]},
            )
            assert renamed.status_code == 200
            assert renamed.json()["status"] == "published"
            assert renamed.json()["activeRuleVersion"] == published["activeRuleVersion"]

            changed = client.patch(
                f"/api/v1/collectors/{collector['id']}",
                headers={"Idempotency-Key": "change-collector-intent-0001"},
                json={"name": "Renamed", "intent": "Collect a revised field set", "sourceUrl": published["sourceUrl"]},
            )
            assert changed.status_code == 200
            assert changed.json()["status"] == "draft"
            assert changed.json()["candidate"] is None
            assert changed.json()["activeRuleVersion"] == published["activeRuleVersion"]
            blocked = client.post(
                f"/api/v1/collectors/{collector['id']}/runs",
                headers={"Idempotency-Key": "run-after-definition-edit"},
            )
            assert blocked.status_code == 409
            assert blocked.json()["code"] == "RULE_NOT_PUBLISHED"
    finally:
        app_module.store = original


def test_direct_rule_edit_creates_new_candidate_without_mutating_published_rule(tmp_path: Path) -> None:
    original = app_module.store
    original_artifact_path = app_module.settings.artifact_path
    app_module.store = Store(tmp_path / "api.db")
    app_module.settings.artifact_path = tmp_path / "artifacts"
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = ready_review_collector(app_module.store)
            candidate = collector["candidate"]
            operation = {
                "id": "op_edit_candidate_samples",
                "kind": "explore",
                "status": "succeeded",
                "resourceId": collector["id"],
            }
            app_module.store.save_operation(operation, collector["id"])
            artifact_dir = app_module.settings.artifact_path / operation["id"]
            artifact_dir.mkdir(parents=True)
            artifact_dir.joinpath("list-001.html").write_text(
                '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">A</a>'
                '<time datetime="2026-08-31T00:00:00Z"></time></li></ul>',
                encoding="utf-8",
            )
            artifact_dir.joinpath("detail-001.html").write_text(
                '<h1 class="notice-title">A</h1><div class="meta"><span data-field="buyer">B</span>'
                '<time datetime="2026-08-31T00:00:00Z"></time></div>',
                encoding="utf-8",
            )
            output_fields = candidate["gatherSpec"]["collect"]["detail"]["fields"]
            list_fields = candidate["gatherSpec"]["collect"]["list"]["fields"]
            body = {
                "listSelector": "css:ul.notice-list > li",
                "detailLinkSelector": "css:a.notice-title::attr(href)",
                "pagination": {
                    "type": "next_link",
                    "selector": "css:a.next::attr(href)",
                    "maxPages": 12,
                    "allowCrossHost": False,
                },
                "listFields": [
                    {
                        "key": key,
                        "selector": "css:a.notice-title::text" if key == "listTitle" else value["selector"],
                    }
                    for key, value in list_fields.items()
                ],
                "fields": [
                    {"key": field["key"], "selector": output_fields[field["key"]]["selector"]}
                    for field in candidate["fields"]
                ],
            }
            edited = client.patch(
                f"/api/v1/collectors/{collector['id']}/candidate-rule",
                headers={"Idempotency-Key": "edit-candidate-rule-0001"},
                json=body,
            )
            assert edited.status_code == 200
            updated = edited.json()
            assert updated["status"] == "ready_review"
            assert updated["candidate"]["id"] != candidate["id"]
            assert updated["candidate"]["digest"] != candidate["digest"]
            assert updated["candidate"]["pagination"]["maxPages"] == 12
            assert updated["candidate"]["gatherSpec"]["collect"]["list"]["itemsSelector"] == body["listSelector"]
            assert updated["candidate"]["gatherSpec"]["collect"]["list"]["fields"]["listTitle"]["selector"] == "css:a.notice-title::text"
            assert updated["candidate"]["gatherSpec"]["compiler"]["overrideRefs"]
            app_module.contracts.validate_gather_spec(updated["candidate"]["gatherSpec"])

            replayed = client.patch(
                f"/api/v1/collectors/{collector['id']}/candidate-rule",
                headers={"Idempotency-Key": "edit-candidate-rule-0001"},
                json=body,
            )
            assert replayed.status_code == 200
            assert replayed.headers["Idempotency-Replayed"] == "true"
            assert replayed.json()["candidate"]["id"] == updated["candidate"]["id"]

            mismatched = copy.deepcopy(body)
            mismatched["listFields"] = [
                {**field, "selector": "css:a.other::attr(href)"} if field["key"] == "detailUrl" else field
                for field in mismatched["listFields"]
            ]
            rejected = client.patch(
                f"/api/v1/collectors/{collector['id']}/candidate-rule",
                headers={"Idempotency-Key": "edit-candidate-rule-invalid-detail-url"},
                json=mismatched,
            )
            assert rejected.status_code == 422
            assert rejected.json()["code"] == "VALIDATION_FAILED"
    finally:
        app_module.store = original
        app_module.settings.artifact_path = original_artifact_path


def test_openapi_external_gather_schema_is_served() -> None:
    with TestClient(app_module.app) as client:
        openapi = client.get("/openapi.json")
        schema = client.get("/gather-spec.schema.json")
        assert openapi.json()["x-contract-id"] == "extrio.control-plane.v1"
        assert schema.json()["$id"] == "https://schemas.extrio.dev/gather-spec.v1.schema.json"


def test_frozen_openapi_paths_match_implemented_api_routes() -> None:
    def path_shape(path: str) -> str:
        return re.sub(r"\{[^}]+\}", "{}", path)

    contract = {
        (method.upper(), path_shape(f"/api/v1{path}"))
        for path, path_item in app_module.contracts.openapi["paths"].items()
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    implemented = {
        (method, path_shape(route.path))
        for route in app_module.app.routes
        if getattr(route, "path", "").startswith("/api/v1")
        for method in (getattr(route, "methods", None) or set())
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert implemented == contract


def test_rule_version_ids_are_unique_across_collectors() -> None:
    first = app_module.next_rule_version_id("collector_alpha", 1)
    second = app_module.next_rule_version_id("collector_beta", 1)
    assert first != second
    assert first.endswith("_v1")


def test_startup_backfills_integrity_for_legacy_published_collector(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        collector = ready_review_collector(app_module.store)
        decisions = {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}
        collector.update(status="published", activeRuleVersion="rule_legacy_v1", reviewDecisions=decisions)
        app_module.store.save_collector(collector)

        with TestClient(app_module.app):
            rule_version = app_module.store.get_rule_version("rule_legacy_v1")
            attestation = app_module.store.latest_rule_attestation("rule_legacy_v1")
            assert rule_version and attestation
            assert attestation["ruleDigest"] == rule_version["ruleDigest"]
            assert app_module.store.list_audit_events()[0]["action"] == "rule.integrity_bootstrapped"
    finally:
        app_module.store = original


def test_startup_backfills_nullable_policy_context_for_legacy_runs(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        collector = app_module.store.create_collector("Legacy", "Collect", "https://example.com/list", "example.com")
        legacy_run = {
            "id": "run_legacy",
            "collectorId": collector["id"],
            "items": [
                {
                    "id": "item_legacy",
                    "lineage": {"runId": "run_legacy"},
                }
            ],
        }
        app_module.store.save_run(legacy_run)
        app_module.store.save_items("run_legacy", legacy_run["items"])
        app_module.store.save_operation(
            {
                "id": "op_legacy",
                "metrics": {"listPagesFetched": 1, "detailUrlsDiscovered": 2, "detailPagesFetched": 2, "warningCount": 0},
            },
            collector["id"],
        )

        with TestClient(app_module.app):
            run = app_module.store.get_run("run_legacy")
            assert run["policyContextStatus"] == "legacy_unavailable"
            assert run["policyVersion"] is None
            assert run["checkpointBefore"] is None
            assert run["recordsOutsideWindow"] == 0
            assert run["items"][0]["changeType"] is None
            assert app_module.store.get_item("item_legacy")["changeType"] is None
            assert app_module.store.get_operation("op_legacy")["metrics"]["unchangedItems"] == 0
    finally:
        app_module.store = original


def test_concurrent_exploration_retries_share_one_operation(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")

            def submit():
                return client.post(
                    f"/api/v1/collectors/{collector['id']}/explorations",
                    headers={"Idempotency-Key": "concurrent-explore-001"},
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda _index: submit(), range(2)))
            assert [response.status_code for response in responses] == [202, 202]
            assert len({response.json()["id"] for response in responses}) == 1
            with app_module.store.connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
    finally:
        app_module.store = original


def test_publish_persists_integrity_bundle_and_run_freezes_it(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = ready_review_collector(app_module.store)
            decisions = {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}
            published = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "publish-integrity-0001"},
                json={"reviewDecisions": decisions},
            )
            assert published.status_code == 200
            replayed = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "publish-integrity-0001"},
                json={"reviewDecisions": decisions},
            )
            assert replayed.status_code == 200
            assert replayed.headers["Idempotency-Replayed"] == "true"
            rule_version_id = published.json()["activeRuleVersion"]
            rule_version = app_module.store.get_rule_version(rule_version_id)
            assert rule_version and rule_version["ruleDigest"] == rule_version["gatherSpec"]["integrity"]["ruleDigest"]
            attestation = app_module.store.latest_rule_attestation(rule_version_id)
            assert attestation and attestation["ruleDigest"] == rule_version["ruleDigest"]
            assert app_module.store.list_audit_events()[0]["action"] == "rule.published"

            accepted = client.post(
                f"/api/v1/collectors/{collector['id']}/runs",
                headers={"Idempotency-Key": "run-integrity-0001"},
            )
            assert accepted.status_code == 202
            run = client.get(f"/api/v1/runs/{accepted.json()['resourceId']}").json()
            assert run["integrityStatus"] == "verified"
            assert run["ruleAttestationId"] == attestation["attestationId"]
            policy = published.json()["collectionPolicy"]
            assert run["policyVersion"] == policy["id"]
            assert run["policyDigest"] == policy["digest"]
            assert run["executionMode"] == "initial"
            assert run["windowStart"] == (
                datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=policy["initialWindowDays"])
            ).isoformat()
            assert run["checkpointBefore"] is None
            assert run["checkpointAfter"] is None
            job = app_module.store.claim_job(60)
            assert job and job["payload"]["integrity"]["attestationId"] == attestation["attestationId"]
            assert job["payload"]["integrity"]["ruleDigest"] == rule_version["ruleDigest"]
            assert job["payload"]["policyVersionId"] == policy["id"]
            assert job["payload"]["policyDigest"] == policy["digest"]
    finally:
        app_module.store = original


def test_retired_signing_key_blocks_new_runs(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = ready_review_collector(app_module.store)
            decisions = {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}
            published = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "publish-integrity-0002"},
                json={"reviewDecisions": decisions},
            )
            assert published.status_code == 200
            app_module.store.update_signing_key_status(
                app_module.rule_signer.key_id,
                "retired",
                actor_id="security_officer_demo",
                request_id="req_retire_key",
            )

            rejected = client.post(
                f"/api/v1/collectors/{collector['id']}/runs",
                headers={"Idempotency-Key": "run-integrity-0002"},
            )
            assert rejected.status_code == 409
            assert rejected.json()["code"] == "RULE_ATTESTATION_INVALID"
            assert app_module.store.list_audit_events()[0]["action"] == "signing_key.retired"
    finally:
        app_module.store = original


@pytest.mark.asyncio
async def test_worker_revalidates_fixed_attestation_before_source_request(tmp_path: Path) -> None:
    class RuntimeMustNotRun:
        called = False

        async def run(self, *_args, **_kwargs):
            self.called = True
            raise AssertionError("runtime must not execute after integrity revocation")

    original = app_module.store
    app_module.store = Store(tmp_path / "api.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            collector = ready_review_collector(app_module.store)
            decisions = {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}
            assert (
                client.post(
                    f"/api/v1/collectors/{collector['id']}/publish",
                    headers={"Idempotency-Key": "publish-integrity-0003"},
                    json={"reviewDecisions": decisions},
                ).status_code
                == 200
            )
            assert (
                client.post(
                    f"/api/v1/collectors/{collector['id']}/runs",
                    headers={"Idempotency-Key": "run-integrity-0003"},
                ).status_code
                == 202
            )
            job = app_module.store.claim_job(60)
            assert job
            app_module.store.update_signing_key_status(
                app_module.rule_signer.key_id,
                "compromised",
                actor_id="security_officer_demo",
                request_id="req_compromise_key",
            )

            runtime = RuntimeMustNotRun()
            worker = Worker.__new__(Worker)
            worker.store = app_module.store
            worker.contracts = app_module.contracts
            worker.runtime = runtime
            with pytest.raises(IntegrityError, match="not trusted"):
                await worker.process(job)
            assert runtime.called is False
    finally:
        app_module.store = original
