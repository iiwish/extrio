import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.collection_fields import DEFAULT_COLLECTION_FIELDS
from extrio.store import Store


@pytest.fixture(params=["sqlite", "postgresql"] if os.environ.get("EXTRIO_TEST_DATABASE_URL") else ["sqlite"])
def client(tmp_path, monkeypatch, request):
    base_url = os.environ.get("EXTRIO_TEST_DATABASE_URL")
    database_name = f"extrio_g2_{uuid.uuid4().hex[:12]}"
    database_url = None
    if request.param == "postgresql":
        with psycopg.connect(base_url, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{database_name}"')
        database_url = f"{base_url.rsplit('/', 1)[0]}/{database_name}"
    store = Store(tmp_path / "api_versions.db", database_url=database_url)
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "settings", app_module.settings.model_copy(update={"seed_demo": False}))
    try:
        with TestClient(app_module.app) as client:
            yield client
    finally:
        if database_url:
            with psycopg.connect(base_url, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE "{database_name}" WITH (FORCE)')


def command(client: TestClient, method: str, path: str, body: dict | None = None, key: str = "default-command-key-16"):
    req_headers = {"Idempotency-Key": key}
    return client.request(method, path, json=body, headers=req_headers)


def test_published_collection_versions_are_immutable_in_storage(client):
    from test_collection_migration import setup_migration

    _, _, frozen = setup_migration(client)
    for sql in ("UPDATE collection_versions SET data=data WHERE id=?", "DELETE FROM collection_versions WHERE id=?"):
        with pytest.raises(Exception, match="immutable"):
            with app_module.store.transaction() as connection:
                connection.execute(sql, (frozen["id"],))
    assert app_module.store.get_collection_version(frozen["id"]) == frozen


def test_publish_collection_version_lifecycle(client):
    # 1. 创建需求
    resp = command(client, "POST", "/api/v1/collections", {"name": "招标需求", "intent": "抓取采购信息"}, "key-create-collection-1")
    assert resp.status_code == 201
    col = resp.json()
    col_id = col["id"]
    assert col["activeVersionId"] is None
    assert col["latestVersionNumber"] == 0

    # 1.1 无草稿时发布失败
    no_draft_resp = command(
        client,
        "POST",
        f"/api/v1/collections/{col_id}/publish-version",
        {"revision": 1},
        "key-pub-nodraft-1",
    )
    assert no_draft_resp.status_code == 422
    assert no_draft_resp.json()["code"] == "NO_FIELD_DRAFT"

    # 1.2 保存草稿（使用默认招标模版字段）
    patch_init_resp = command(
        client,
        "PATCH",
        f"/api/v1/collections/{col_id}",
        {"revision": 1, "fieldDraft": {"fields": DEFAULT_COLLECTION_FIELDS}},
        "key-patch-init-draft-1",
    )
    assert patch_init_resp.status_code == 200

    # 2. 发布版本 v1
    v1_resp = command(
        client,
        "POST",
        f"/api/v1/collections/{col_id}/publish-version",
        {"revision": 2, "note": "初始发布 v1"},
        "key-publish-version-1",
    )
    assert v1_resp.status_code == 201
    v1 = v1_resp.json()
    assert v1["versionNumber"] == 1
    assert v1["collectionId"] == col_id
    assert v1["note"] == "初始发布 v1"
    assert v1["outputContractDigest"].startswith("sha256:")
    assert len(v1["fields"]) == 8
    assert "title" in [f["key"] for f in v1["fields"]]

    # 3. 幂等重放
    replay_resp = command(
        client,
        "POST",
        f"/api/v1/collections/{col_id}/publish-version",
        {"revision": 2, "note": "初始发布 v1"},
        "key-publish-version-1",
    )
    assert replay_resp.status_code == 201
    assert replay_resp.headers.get("Idempotency-Replayed") == "true"
    assert replay_resp.json()["id"] == v1["id"]

    # 4. 获取需求详情，检查 activeVersion
    detail = client.get(f"/api/v1/collections/{col_id}").json()
    assert detail["activeVersionId"] == v1["id"]
    assert detail["latestVersionNumber"] == 1
    assert detail["revision"] == 3
    assert detail["activeVersion"]["id"] == v1["id"]
    assert detail["activeVersion"]["fieldCount"] == 8

    # 5. 修改草稿并发布 v2
    patch_resp = command(
        client,
        "PATCH",
        f"/api/v1/collections/{col_id}",
        {
            "revision": 3,
            "fieldDraft": {
                "fields": [
                    {
                        "key": "item_code",
                        "label": "项目编号",
                        "type": "string",
                        "required": True,
                        "identity": True,
                        "fingerprint": True,
                        "description": "项目编号",
                    },
                    {
                        "key": "amount",
                        "label": "预算金额",
                        "type": "number",
                        "required": False,
                        "identity": False,
                        "fingerprint": False,
                        "description": "预算",
                    },
                ]
            },
        },
        "key-update-field-draft-1",
    )
    assert patch_resp.status_code == 200

    v2_resp = command(
        client,
        "POST",
        f"/api/v1/collections/{col_id}/publish-version",
        {"revision": 4, "note": "精简字段为项目编号与预算"},
        "key-publish-version-2",
    )
    assert v2_resp.status_code == 201
    v2 = v2_resp.json()
    assert v2["versionNumber"] == 2
    assert v2["id"] != v1["id"]
    assert len(v2["fields"]) == 2

    # 6. 查询版本列表与单版本详情
    list_resp = client.get(f"/api/v1/collections/{col_id}/versions")
    assert list_resp.status_code == 200
    versions = list_resp.json()["items"]
    assert len(versions) == 2
    assert versions[0]["versionNumber"] == 2
    assert versions[1]["versionNumber"] == 1

    get_v1 = client.get(f"/api/v1/collections/{col_id}/versions/{v1['id']}")
    assert get_v1.status_code == 200
    assert get_v1.json()["id"] == v1["id"]

    # 7. 审计日志验证
    events = [e for e in app_module.store.list_audit_events() if e["targetType"] == "collection_version"]
    assert len(events) == 2
    assert {e["action"] for e in events} == {"collection_version.published"}
    assert app_module.store.verify_audit_chain(app_module.settings.tenant_id)


def test_source_version_alignment(client):
    # 创建需求，配置草稿并发布 v1
    col = command(client, "POST", "/api/v1/collections", {"name": "对齐测试需求", "intent": "目标"}, "key-col-alignment-1").json()
    command(
        client,
        "PATCH",
        f"/api/v1/collections/{col['id']}",
        {"revision": 1, "fieldDraft": {"fields": DEFAULT_COLLECTION_FIELDS}},
        "key-patch-col-align-1",
    )
    v1 = command(client, "POST", f"/api/v1/collections/{col['id']}/publish-version", {"revision": 2}, "key-pub-alignment-1").json()

    # 新建来源，强绑定当前已发布的 v1
    batch_resp = command(
        client,
        "POST",
        "/api/v1/collectors/batch",
        {
            "collectionId": col["id"],
            "collectionName": col["name"],
            "intent": col["intent"],
            "sources": [{"entryUrl": "https://example.com/source-1", "mode": "exact"}],
        },
        "key-batch-alignment-1",
    )
    assert batch_resp.status_code == 200
    source1 = batch_resp.json()["results"][0]["collector"]
    assert source1["collectionVersion"] == v1["id"]

    # 此时检查来源契约投影：已对齐
    contracts_resp = client.get(f"/api/v1/collections/{col['id']}").json()["sourceContracts"]
    assert len(contracts_resp) == 1
    assert contracts_resp[0]["sourceId"] == source1["id"]
    assert contracts_resp[0]["sourceVersion"] == v1["id"]
    assert contracts_resp[0]["targetVersionNumber"] == 1
    assert contracts_resp[0]["isAligned"] is True

    # 需求发布 v2
    v2 = command(client, "POST", f"/api/v1/collections/{col['id']}/publish-version", {"revision": 3}, "key-pub-alignment-2").json()
    assert v2["versionNumber"] == 2

    # 检查来源契约投影：未对齐（sourceVersion=v1, targetVersionNumber=2, isAligned=False）
    contracts_v2 = client.get(f"/api/v1/collections/{col['id']}").json()["sourceContracts"]
    assert contracts_v2[0]["isAligned"] is False
    assert contracts_v2[0]["targetVersionNumber"] == 2
    assert contracts_v2[0]["sourceVersion"] == v1["id"]
    command(client, "PATCH", f"/api/v1/collections/{col['id']}", {"revision": 4, "fieldDraft": {"fields": []}}, "key-clear-editable-draft")
    detail = client.get(f"/api/v1/collectors/{source1['id']}").json()
    assert detail["collectionVersion"] == v1["id"]
    assert detail["collectionFields"] == v1["fields"]


def test_publish_collection_version_validation(client):
    col = command(client, "POST", "/api/v1/collections", {"name": "校验测试", "intent": "校验"}, "key-validation-col").json()

    # 1. 冲突版本号
    err_conf = command(client, "POST", f"/api/v1/collections/{col['id']}/publish-version", {"revision": 99}, "key-pub-conflict-99")
    assert err_conf.status_code == 409
    assert err_conf.json()["code"] == "COLLECTION_CONFLICT"

    # 2. 已归档不可发布
    command(client, "PATCH", f"/api/v1/collections/{col['id']}", {"revision": 1, "status": "archived"}, "key-patch-archive-1")
    err_arch = command(client, "POST", f"/api/v1/collections/{col['id']}/publish-version", {"revision": 2}, "key-pub-archived-2")
    assert err_arch.status_code == 409
    assert err_arch.json()["code"] == "COLLECTION_ARCHIVED"
