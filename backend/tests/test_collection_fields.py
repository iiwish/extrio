from copy import deepcopy

from test_collections import client as collection_client
from test_collections import command

import extrio.app as app_module

client = collection_client


def field(key="title", **changes):
    return {"key": key, "label": "Title", "type": "string", "required": True,
            "identity": True, "fingerprint": True, "description": "Business title", **changes}


def test_field_draft_persists_and_does_not_change_sources(client):
    store = app_module.store
    source = store.create_collector("Site", "Goal", "https://example.com/list", "example.com")
    original = deepcopy(store.get_collector(source["id"]))
    path = f"/api/v1/collections/{source['collectionId']}"
    response = command(client, "PATCH", path, {"revision": 1, "fieldDraft": {"fields": [field()]}})
    assert response.status_code == 200, response.text
    assert client.get(path).json()["fieldDraft"]["fields"] == [field()]
    assert store.get_collector(source["id"]) == original
    assert command(client, "PATCH", path, {"revision": 1, "fieldDraft": {"fields": []}}, "stale-field-command-key").status_code == 409
    assert command(client, "PATCH", path, {"revision": 2, "status": "archived"}, "archive-field-command-key").status_code == 200
    assert command(client, "PATCH", path, {"revision": 3, "fieldDraft": {"fields": []}}, "archived-field-command-key").status_code == 409


def test_field_draft_validation(client):
    value = command(client, "POST", "/api/v1/collections", {"name": "Need", "intent": "Goal"}).json()
    path = f"/api/v1/collections/{value['id']}"
    for fields in [[field(), field()], [field("invalid key")], [field(type="code")],
                   [field(required=False)], [field(identity="true")], [field(extra="unexpected")]]:
        assert command(client, "PATCH", path, {"revision": 1, "fieldDraft": {"fields": fields}}).status_code == 422
    assert command(client, "PATCH", path, {"revision": 1, "fieldDraft": {"fields": []}}).status_code == 200


def test_execution_contract_uses_published_rule_not_candidate(client):
    store = app_module.store
    source = store.create_collector("Site", "Goal", "https://example.com/list", "example.com")
    source["activeRuleVersion"] = "rule_real"
    source["candidate"] = {"gatherSpec": {"contract": {"normalizedItemSchema": {"properties": {"wrong": {"type": "string"}}}}}}
    store.save_collector(source)
    spec = {"collect": {"list": {"fields": {"detailUrl": {"label": "Detail URL", "valueType": "url"}}}},
            "contract": {"normalizedItemSchema": {"properties": {"detailUrl": {"type": "string"}, "amount": {"type": "number"}},
                                                   "required": ["detailUrl"]}, "identityFields": ["detailUrl"],
                         "fingerprintFields": ["amount"], "quality": {"emptyResultPolicy": "suspect"}}}
    with store.transaction() as conn:
        conn.execute("INSERT INTO rule_versions(id, tenant_id, collector_id, rule_digest, data, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                     ("rule_real", "local", source["id"], "digest",
                      store.dialect.json_param({"id": "rule_real", "gatherSpec": spec}), "2026-09-06"))
    result = client.get(f"/api/v1/collections/{source['collectionId']}").json()["sourceContracts"][0]
    assert result["state"] == "published"
    assert [item["key"] for item in result["fields"]] == ["detailUrl", "amount"]
    assert result["fields"][0]["label"] == "Detail URL"
    assert result["fields"][1]["type"] == "number"
    assert result["quality"] == spec["contract"]["quality"]
    source["activeRuleVersion"] = "missing_rule"
    store.save_collector(source)
    missing = client.get(f"/api/v1/collections/{source['collectionId']}").json()["sourceContracts"][0]
    assert missing["state"] == "unavailable" and missing["fields"] == []
