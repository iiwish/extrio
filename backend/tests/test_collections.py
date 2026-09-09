from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.store import Store


def test_independent_collection_crud_and_revision(tmp_path: Path):
    store = Store(tmp_path / "collections.db")
    store.initialize()
    value = store.create_collection("Need", "Collect notices")
    assert value["sourceCount"] == 0
    assert store.get_collection(value["id"])["intent"] == "Collect notices"
    changed = store.change_collection(value["id"], 1, {"name": "Renamed", "intent": "New goal"})
    assert changed["revision"] == 2
    with pytest.raises(ValueError, match="COLLECTION_CONFLICT"):
        store.change_collection(value["id"], 1, {"name": "Stale"})
    store.delete_collection(value["id"], 2)
    assert store.get_collection(value["id"]) is None


def test_collection_preserves_sources_and_rejects_unsafe_delete(tmp_path: Path):
    store = Store(tmp_path / "collections.db")
    store.initialize()
    source = store.create_collector("Site", "Original extraction", "https://example.com/list", "example.com")
    value = store.get_collection(source["collectionId"])
    assert value["sourceCount"] == 1
    with pytest.raises(ValueError, match="COLLECTION_HAS_SOURCES"):
        store.delete_collection(value["id"], value["revision"])
    store.change_collection(value["id"], 1, {"name": "Renamed", "intent": "Updated goal"})
    updated_source = store.get_collector(source["id"])
    assert updated_source["collectionName"] == "Renamed"
    assert updated_source["intent"] == source["intent"]
    assert updated_source["candidate"] == source["candidate"]
    archived = store.change_collection(value["id"], 2, {"status": "archived"})
    with pytest.raises(ValueError, match="COLLECTION_ARCHIVED"):
        store.create_collector("Other", "Goal", "https://example.com/other", "example.com",
                               collection_id=value["id"], require_existing_collection=True)
    store.change_collection(value["id"], archived["revision"], {"status": "active"})
    assert store.get_collector(source["id"])["intent"] == "Original extraction"


def test_legacy_backfill_is_idempotent_and_keeps_multiple_source_intents(tmp_path: Path):
    store = Store(tmp_path / "collections.db")
    store.initialize()
    first = store.create_collector("One", "Goal A", "https://example.com/a", "example.com")
    store.create_collector("Two", "Goal B", "https://example.com/b", "example.com")
    with store.transaction() as conn:
        conn.execute("DELETE FROM collections")
    store.initialize()
    value = store.get_collection(first["collectionId"])
    assert "Goal A" in value["intent"] and "Goal B" in value["intent"]
    store.change_collection(value["id"], value["revision"], {"name": "Canonical"})
    store.initialize()
    assert store.get_collection(value["id"])["name"] == "Canonical"


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "api.db")
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "settings", app_module.settings.model_copy(update={"seed_demo": False}))
    with TestClient(app_module.app) as client:
        yield client


def command(client, method, path, body, key="collection-command-key"):
    return client.request(method, path, json=body, headers={"Idempotency-Key": key})


def test_api_crud_and_durable_idempotency(client):
    body = {"name": "Independent", "intent": "Business goal"}
    response = command(client, "POST", "/api/v1/collections", body)
    assert response.status_code == 201
    value = response.json()
    path = f"/api/v1/collections/{value['id']}"
    replay = command(client, "POST", "/api/v1/collections", body)
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == value
    assert command(client, "POST", "/api/v1/collections", {**body, "name": "Other"}).status_code == 409
    assert client.get(path).json()["sources"] == []
    assert len(client.get("/api/v1/collections").json()["items"]) == 1
    changed = command(client, "PATCH", path, {"revision": 1, "name": "Edited"})
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2
    stale = command(client, "PATCH", path, {"revision": 1, "name": "Stale"}, "stale-command-key")
    assert stale.json()["code"] == "COLLECTION_CONFLICT"
    assert command(client, "DELETE", path, {"revision": 2}).status_code == 200
    assert command(client, "DELETE", path, {"revision": 2}).headers["Idempotency-Replayed"] == "true"
    assert client.get(path).status_code == 404
    events = [event for event in app_module.store.list_audit_events() if event["targetId"] == value["id"]]
    assert len(events) == 3
    assert {event["action"] for event in events} == {"collection.created", "collection.updated", "collection.deleted"}
    assert app_module.store.verify_audit_chain(app_module.settings.tenant_id)


def test_empty_requirement_can_receive_sources_and_archive_preserves_them(client):
    value = command(client, "POST", "/api/v1/collections", {"name": "Need", "intent": "Original"}).json()
    path = f"/api/v1/collections/{value['id']}"
    command(client, "PATCH", path, {"revision": 1, "name": "Current", "intent": "Current goal"})
    batch = {"collectionId": value["id"], "collectionName": "Stale", "intent": "Stale",
             "sources": [{"entryUrl": "https://example.com/list", "mode": "exact"}]}
    response = command(client, "POST", "/api/v1/collectors/batch", batch)
    assert response.status_code == 200, response.text
    source = response.json()["results"][0]["collector"]
    assert source["collectionName"] == "Current" and source["intent"] == "Current goal"
    assert command(client, "DELETE", path, {"revision": 2}).json()["code"] == "COLLECTION_HAS_SOURCES"
    assert command(client, "PATCH", path, {"revision": 2, "status": "archived"}, "archive-command-key").status_code == 200
    assert command(client, "POST", "/api/v1/collectors/batch", batch, "archived-source-key").json()["code"] == "COLLECTION_ARCHIVED"
    assert command(client, "PATCH", path, {"revision": 3, "intent": "Not allowed"}, "edit-archived-key").status_code == 409
    assert client.get(path).json()["sources"][0]["id"] == source["id"]
    assert command(client, "PATCH", path, {"revision": 3, "status": "active"}, "restore-command-key").status_code == 200


@pytest.mark.parametrize("body", [{"name": "", "intent": "A"}, {"name": 123, "intent": "A"},
                                   {"name": "A", "intent": "B", "sources": []}])
def test_create_validation(client, body):
    assert command(client, "POST", "/api/v1/collections", body).status_code == 422


@pytest.mark.parametrize("body", [{"revision": True, "name": "A"}, {"revision": 1, "status": []},
                                   {"revision": 1}, {"revision": 1, "status": "archived", "name": "A"}])
def test_patch_validation(client, body):
    assert command(client, "PATCH", "/api/v1/collections/missing", body).status_code == 422


def test_permissions_and_idempotency_requirement(client, monkeypatch):
    assert client.post("/api/v1/collections", json={"name": "A", "intent": "B"}).status_code == 400
    monkeypatch.setattr(app_module, "settings", app_module.settings.model_copy(update={"auth_enabled": True, "auth_cookie_secure": False}))
    assert client.get("/api/v1/collections").status_code == 401
    client.post("/api/v1/auth/setup", json={"username": "admin", "password": "test-pass-12345"})
    response = command(client, "POST", "/api/v1/users", {"username": "viewer", "password": "test-pass-12345", "role": "viewer"})
    assert response.status_code == 201, response.text
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "viewer", "password": "test-pass-12345"})
    assert client.get("/api/v1/collections").status_code == 200
    for method, path, body in [("POST", "/api/v1/collections", {"name": "A", "intent": "B"}),
                                ("PATCH", "/api/v1/collections/missing", {"revision": 1, "name": "A"}),
                                ("DELETE", "/api/v1/collections/missing", {"revision": 1})]:
        assert command(client, method, path, body).status_code == 403


def test_concurrent_idempotency_and_source_delete_race(tmp_path):
    store = Store(tmp_path / "race.db")
    store.initialize()
    body = {"name": "Need", "intent": "Goal"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: store.collection_command("POST", None, body, "same-key"), range(2)))
    assert receipts[0][1]["id"] == receipts[1][1]["id"]
    assert len(store.list_collections()) == 1
    value = receipts[0][1]
    barrier = Barrier(2)

    def create_source():
        barrier.wait()
        try:
            store.create_collector("Site", "Goal", "https://example.com/list", "example.com",
                                   collection_id=value["id"], require_existing_collection=True)
            return "created"
        except ValueError as exc:
            return str(exc)

    def delete_requirement():
        barrier.wait()
        try:
            store.delete_collection(value["id"], value["revision"])
            return "deleted"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        source = pool.submit(create_source)
        deletion = pool.submit(delete_requirement)
        outcome = source.result(), deletion.result()
    assert outcome in {("created", "COLLECTION_HAS_SOURCES"), ("COLLECTION_NOT_FOUND", "deleted")}


def test_detail_includes_sources_beyond_legacy_list_limit(client):
    store = app_module.store
    value = store.create_collection("Many sources", "Goal")
    for i in range(51):
        store.create_collector(f"Source {i}", "Goal", f"https://example.com/list/{i}", "example.com",
                               collection_id=value["id"], require_existing_collection=True)
    detail = client.get(f"/api/v1/collections/{value['id']}").json()
    assert detail["sourceCount"] == len(detail["sources"]) == 51
    assert client.get("/api/v1/collections").json()["items"][0]["sourceCount"] == 51
