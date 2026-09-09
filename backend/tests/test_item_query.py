import json

from test_api_output import output_client, output_item, seed_items


def seed_entity_query(store):
    first = store.create_collector("One", "Collect", "https://one.example.com/list", "one.example.com")
    other = store.create_collector("Other", "Collect", "https://other.example.com/list", "other.example.com")
    rows = [
        output_item(f"old_{i:03}", first["id"], "run_old", "2026-09-01 10:00", f"key_{i:03}")
        for i in range(205)
    ]
    for row in rows:
        row.update(sourceHost="one.example.com", title="Hospital 100%_ procurement")
    seed_items(store, first["id"], "run_old", rows)
    latest = output_item("latest", first["id"], "run_new", "2026-09-02 10:00", "key_000", decision="rejected")
    latest.update(sourceHost="one.example.com", title="Changed title", content="Changed body")
    seed_items(store, first["id"], "run_new", [latest])
    other_row = output_item("other", other["id"], "run_other", "2026-09-03 10:00", "key_000")
    other_row.update(sourceHost="other.example.com", title="Hospital 100XX procurement")
    seed_items(store, other["id"], "run_other", [other_row])
    return first, other


def test_entity_pages_cover_old_entities_and_preserve_collector_identity(tmp_path):
    with output_client(tmp_path) as (store, client):
        seed_entity_query(store)
        first = client.get("/api/v1/items", params={"view": "entities", "limit": 200}).json()
        second = client.get("/api/v1/items", params={"view": "entities", "limit": 200, "cursor": first["nextCursor"]}).json()
        rows = first["items"] + second["items"]
        assert first["total"] == 206
        assert len(rows) == 206
        assert len({(row["collectorId"], row["entityKey"]) for row in rows}) == 206
        assert "old_000" not in {row["id"] for row in rows}
        assert {"latest", "other"}.issubset({row["id"] for row in rows})
        assert second["nextCursor"] is None
        assert set(first["facets"]["sourceHosts"]) == {"one.example.com", "other.example.com"}
        assert client.get("/api/v1/items", params={"view": "invalid"}).status_code == 422


def test_entity_search_and_export_share_filters_after_latest_selection(tmp_path):
    with output_client(tmp_path) as (store, client):
        first, _ = seed_entity_query(store)
        filters = {"view": "entities", "q": "hOsPiTaL 100%_", "sourceHost": "one.example.com", "decision": "accepted"}
        response = client.get("/api/v1/items", params={**filters, "limit": 200})
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 204
        assert "old_000" not in {item["id"] for item in page["items"]}
        tail = client.get("/api/v1/items", params={**filters, "limit": 200, "cursor": page["nextCursor"]}).json()
        expected = page["items"] + tail["items"]
        exported = client.get("/api/v1/items/export", params={**filters, "format": "jsonl"})
        assert exported.status_code == 200
        assert [json.loads(line)["id"] for line in exported.text.splitlines()] == [row["id"] for row in expected]
        assert client.get("/api/v1/items", params={**filters, "collectorId": first["id"], "q": "missing"}).json()["total"] == 0
        exact = client.get("/api/v1/items/export", params={"format": "jsonl", "entityKey": "key_000"})
        assert len(exact.text.splitlines()) == 3, "legacy observation exports retain history and exact entityKey semantics"
