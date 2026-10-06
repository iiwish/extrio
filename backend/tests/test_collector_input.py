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
