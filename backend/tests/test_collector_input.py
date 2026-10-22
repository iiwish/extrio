from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_store_pg import pg_store as pg_store

import extrio.app as app_module
from extrio.store import Store


@pytest.fixture(params=["sqlite", "postgres"])
def collector_store(request, tmp_path: Path, monkeypatch):
    if request.param == "postgres":
        store = request.getfixturevalue("pg_store")
    else:
        store = Store(tmp_path / "collector-input.db")
        store.initialize()
    monkeypatch.setattr(app_module, "store", store)
    return store


@pytest.mark.parametrize("field", ["name", "intent"])
@pytest.mark.parametrize("value", [None, 123, True, [], ["QA"], {"text": "QA"}, "", " \t\n"])
def test_create_collector_rejects_invalid_text_without_writes_or_consuming_key(collector_store, field, value):
    body = {"name": " Source ", "intent": " Collect ", "sourceUrl": "https://example.com/input-probe"}
    headers = {"Idempotency-Key": "collector-input-probe-0001"}
    with TestClient(app_module.app, raise_server_exceptions=False) as client:
        before_collectors = collector_store.list_collectors()
        before_collections = collector_store.list_collections()
        response = client.post("/api/v1/collectors", headers=headers, json={**body, field: value})
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "VALIDATION_FAILED"
        assert response.json()["pointer"] == f"/{field}"
        assert response.json()["retryable"] is False
        assert collector_store.list_collectors() == before_collectors
        assert collector_store.list_collections() == before_collections

        corrected = client.post("/api/v1/collectors", headers=headers, json=body)
        assert corrected.status_code == 201, corrected.text
        assert corrected.json()["name"] == "Source"
        assert corrected.json()["intent"] == "Collect"
        replay = client.post("/api/v1/collectors", headers=headers, json=body)
        assert replay.status_code == 201
        assert replay.json()["id"] == corrected.json()["id"]
        assert replay.headers["Idempotency-Replayed"] == "true"


def test_batch_committed_response_replays_and_all_rejected_retry_has_no_phantom_collection(collector_store):
    body = {"collectionName": "Retry notices", "intent": "Collect notices",
            "sources": [{"entryUrl": "https://example.com/retry-notices"}]}
    headers = {"Idempotency-Key": "batch-committed-response-0001"}
    with TestClient(app_module.app) as client:
        first = client.post("/api/v1/collectors/batch", json=body, headers=headers)
        assert first.status_code == 200, first.text
        created = first.json()
        assert created["createdCount"] == 1 and created["rejectedCount"] == 0
        assert client.get(f"/api/v1/collections/{created['collectionId']}").status_code == 200
        collections = collector_store.list_collections()
        collectors = collector_store.list_collectors()

        replay = client.post("/api/v1/collectors/batch", json=body, headers=headers)
        assert replay.status_code == 200 and replay.json() == created
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert collector_store.list_collections() == collections
        assert collector_store.list_collectors() == collectors

        changed = client.post("/api/v1/collectors/batch", json={**body, "collectionName": "Changed"}, headers=headers)
        assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
        assert collector_store.list_collections() == collections
        assert collector_store.list_collectors() == collectors

        rejected = client.post("/api/v1/collectors/batch", json=body,
                               headers={"Idempotency-Key": "batch-committed-response-0002"})
        assert rejected.status_code == 200, rejected.text
        result = rejected.json()
        assert result["createdCount"] == 0 and result["rejectedCount"] == 1
        assert result["results"][0]["error"]["code"] == "SOURCE_ALREADY_EXISTS"
        assert result["collectionId"] is None and result["collectionVersion"] is None
        assert collector_store.list_collections() == collections
        assert collector_store.list_collectors() == collectors


def test_batch_all_rejected_does_not_create_an_empty_requirement(collector_store):
    body = {"collectionName": "Rejected notices", "intent": "Collect notices",
            "sources": [{"entryUrl": "https://example.com/"}, {"entryUrl": "not-a-url"}]}
    headers = {"Idempotency-Key": "batch-all-rejected-0001"}
    with TestClient(app_module.app) as client:
        collections = collector_store.list_collections()
        collectors = collector_store.list_collectors()
        response = client.post("/api/v1/collectors/batch", json=body, headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["createdCount"] == 0 and result["rejectedCount"] == 2
        assert result["collectionId"] is None and result["collectionVersion"] is None
        assert collector_store.list_collections() == collections and collector_store.list_collectors() == collectors
        assert client.post("/api/v1/collectors/batch", json=body, headers=headers).json() == result


def test_batch_existing_requirement_all_rejected_and_partial_success_keep_real_identity(collector_store):
    with TestClient(app_module.app) as client:
        collection_count = len(collector_store.list_collections())
        collector_count = len(collector_store.list_collectors())
        first = client.post("/api/v1/collectors/batch", json={
            "collectionName": "Existing notices", "intent": "Original intent",
            "sources": [{"entryUrl": "https://example.com/first-notice"}]},
            headers={"Idempotency-Key": "batch-existing-identity-0001"})
        assert first.status_code == 200, first.text
        original = first.json()
        body = {"collectionId": original["collectionId"], "collectionName": "Do not replace", "intent": "Do not replace",
                "sources": [{"entryUrl": "https://example.com/first-notice"}]}
        rejected = client.post("/api/v1/collectors/batch", json=body,
                               headers={"Idempotency-Key": "batch-existing-identity-0002"}).json()
        assert rejected["createdCount"] == 0 and rejected["rejectedCount"] == 1
        assert rejected["collectionId"] == original["collectionId"]
        assert rejected["collectionVersion"] == original["collectionVersion"]
        assert client.get(f"/api/v1/collections/{rejected['collectionId']}").status_code == 200
        body["sources"].append({"entryUrl": "https://example.com/second-notice"})
        partial = client.post("/api/v1/collectors/batch", json=body,
                              headers={"Idempotency-Key": "batch-existing-identity-0003"}).json()
        assert partial["createdCount"] == 1 and partial["rejectedCount"] == 1
        collector = partial["results"][1]["collector"]
        assert partial["collectionId"] == original["collectionId"] == collector["collectionId"]
        assert partial["collectionName"] == "Existing notices" and collector["intent"] == "Original intent"
        assert len(collector_store.list_collections()) == collection_count + 1
        assert len(collector_store.list_collectors()) == collector_count + 2
