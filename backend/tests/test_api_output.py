import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.credentials import CredentialCipher
from extrio.store import Store


def output_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "api-output.db")
    store.initialize()
    return store


@contextmanager
def output_client(tmp_path: Path):
    original = app_module.store
    app_module.store = output_store(tmp_path)
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            yield app_module.store, client
    finally:
        app_module.store = original


def output_item(
    item_id: str,
    collector_id: str,
    run_id: str,
    observed_at: str,
    entity_key: str,
    *,
    decision: str = "accepted",
    extracted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "collectorId": collector_id,
        "collectorName": "演示源",
        "sourceHost": "example.com",
        "listTitle": "列表标题",
        "title": f"公告 {item_id}",
        "buyer": "采购单位",
        "region": "北京",
        "publishedAt": "2026-09-01",
        "budget": "100万元",
        "content": "正文内容",
        "extractedData": extracted or {},
        "sourceUrl": f"https://example.com/detail/{entity_key}",
        "decision": decision,
        "changeType": "new" if decision == "accepted" else None,
        "rejectionReason": None,
        "entityKey": entity_key,
        "revision": 1 if decision == "accepted" else None,
        "observedAt": observed_at,
        "changeSummary": [],
        "observationHistory": [],
        "lineage": {"runId": run_id},
    }


def seed_items(store: Store, collector_id: str, run_id: str, items: list[dict[str, Any]]) -> None:
    store.save_run({"id": run_id, "collectorId": collector_id, "status": "succeeded"})
    store.save_items(run_id, items)


def test_items_endpoint_supports_cursor_pagination(tmp_path: Path) -> None:
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
        seed_items(store, collector["id"], "run_one", [
            output_item("item_a1", collector["id"], "run_one", "2026-09-01 10:00", "e1"),
            output_item("item_a2", collector["id"], "run_one", "2026-09-01 10:00", "e2"),
            output_item("item_a3", collector["id"], "run_one", "2026-09-01 09:00", "e3"),
        ])

        first = client.get("/api/v1/items?limit=2")
        assert first.status_code == 200
        body = first.json()
        assert [item["id"] for item in body["items"]] == ["item_a2", "item_a1"]
        assert body["nextCursor"] is not None
        assert body["page"]["nextCursor"] == body["nextCursor"]

        second = client.get(f"/api/v1/items?limit=2&cursor={body['nextCursor']}")
        assert second.status_code == 200
        assert [item["id"] for item in second.json()["items"]] == ["item_a3"]
        assert second.json()["nextCursor"] is None
        assert second.json()["page"]["nextCursor"] is None

        # A page walk without cursor must behave exactly like the legacy shape.
        unpaginated = client.get("/api/v1/items")
        assert [item["id"] for item in unpaginated.json()["items"]] == ["item_a2", "item_a1", "item_a3"]

        invalid = client.get("/api/v1/items?cursor=!!!not-a-cursor!!!")
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "INVALID_CURSOR"
        assert invalid.json()["requestId"]


def test_items_export_csv_has_bom_header_and_union_extracted_columns(tmp_path: Path) -> None:
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
        seed_items(store, collector["id"], "run_one", [
            output_item(
                "item_a1",
                collector["id"],
                "run_one",
                "2026-09-02 10:00",
                "e1",
                extracted={"projectName": "项目甲", "budget": 1200},
            ),
            output_item(
                "item_a2",
                collector["id"],
                "run_one",
                "2026-09-01 10:00",
                "e2",
                extracted={"projectName": "项目乙", "remark": "备注值"},
            ),
        ])

        response = client.get("/api/v1/items/export?format=csv")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert response.headers["content-disposition"] == 'attachment; filename="extrio-items.csv"'
        text = response.content.decode("utf-8")
        assert text.startswith("﻿")
        lines = text.lstrip("﻿").splitlines()
        assert lines[0] == (
            "entityKey,revision,decision,changeType,collectorName,sourceHost,sourceUrl,publishedAt,observedAt,"
            "budget,projectName,remark"
        )
        assert lines[1] == (
            "e1,1,accepted,new,演示源,example.com,https://example.com/detail/e1,2026-09-01,2026-09-02 10:00,"
            "1200,项目甲,"
        )
        assert lines[2] == (
            "e2,1,accepted,new,演示源,example.com,https://example.com/detail/e2,2026-09-01,2026-09-01 10:00,"
            ",项目乙,备注值"
        )


def test_items_export_jsonl_streams_full_items_and_filters(tmp_path: Path) -> None:
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
        other = store.create_collector("Other", "Collect notices", "https://other.example.com/list", "other.example.com")
        seed_items(store, collector["id"], "run_one", [
            output_item("item_a1", collector["id"], "run_one", "2026-09-02 10:00", "e1", extracted={"projectName": "项目甲"}),
            output_item("item_a2", collector["id"], "run_one", "2026-09-01 10:00", "e2", decision="rejected"),
        ])
        seed_items(store, other["id"], "run_other", [
            output_item("item_o1", other["id"], "run_other", "2026-09-03 10:00", "e9"),
        ])

        export = client.get("/api/v1/items/export?format=jsonl")
        assert export.status_code == 200
        assert export.headers["content-type"] == "application/x-ndjson"
        lines = export.content.decode("utf-8").splitlines()
        assert [json.loads(line)["id"] for line in lines] == ["item_o1", "item_a1", "item_a2"]
        assert any("项目甲" in line for line in lines), "JSONL must not escape non-ASCII characters"

        filtered = client.get(f"/api/v1/items/export?format=jsonl&collectorId={collector['id']}&decision=accepted")
        assert [json.loads(line)["id"] for line in filtered.content.decode("utf-8").splitlines()] == ["item_a1"]

        by_entity = client.get("/api/v1/items/export?format=jsonl&entityKey=e2")
        assert [json.loads(line)["id"] for line in by_entity.content.decode("utf-8").splitlines()] == ["item_a2"]

        by_run = client.get("/api/v1/items/export?format=jsonl&runId=run_other")
        assert [json.loads(line)["id"] for line in by_run.content.decode("utf-8").splitlines()] == ["item_o1"]

        invalid_format = client.get("/api/v1/items/export?format=xml")
        assert invalid_format.status_code == 422
        assert invalid_format.json()["code"] == "VALIDATION_FAILED"


def test_items_export_returns_export_too_large_before_streaming(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "EXPORT_ITEMS_CAP", 2)
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
        seed_items(store, collector["id"], "run_one", [
            output_item("item_a1", collector["id"], "run_one", "2026-09-01 10:00", "e1"),
            output_item("item_a2", collector["id"], "run_one", "2026-09-01 10:00", "e2"),
            output_item("item_a3", collector["id"], "run_one", "2026-09-01 09:00", "e3"),
        ])

        response = client.get("/api/v1/items/export?format=csv")
        assert response.status_code == 400
        assert response.json()["code"] == "EXPORT_TOO_LARGE"

        # Narrowing the result back under the cap streams normally again.
        filtered = client.get("/api/v1/items/export?format=jsonl&entityKey=e1")
        assert filtered.status_code == 200


def test_sink_crud_endpoints_hide_the_secret(tmp_path: Path) -> None:
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
        headers = {"Idempotency-Key": "sink-create-000000001"}
        created = client.post(
            f"/api/v1/collectors/{collector['id']}/sinks",
            headers=headers,
            json={"type": "webhook", "url": "https://hooks.example.com/extrio", "secret": "fake-sink-secret-1", "enabled": True},
        )
        assert created.status_code == 201, created.json()
        sink = created.json()
        assert sink["version"] == 1
        assert sink["enabled"] is True
        assert sink["credentialConfigured"] is True
        assert sink["type"] == "webhook"
        assert "secret" not in sink and "secretConfigured" not in sink
        assert "fake-sink-secret-1" not in created.text

        replay = client.post(
            f"/api/v1/collectors/{collector['id']}/sinks",
            headers=headers,
            json={"type": "webhook", "url": "https://hooks.example.com/extrio", "secret": "fake-sink-secret-1", "enabled": True},
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == sink["id"]
        assert replay.headers["Idempotency-Replayed"] == "true"

        missing_key = client.post(f"/api/v1/collectors/{collector['id']}/sinks", json={"url": "https://hooks.example.com/x"})
        assert missing_key.status_code == 400
        assert missing_key.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"

        for index, url in enumerate([
            "ftp://hooks.example.com/x",
            "https://user:pass@hooks.example.com/x",
            "not-a-url",
        ]):
            rejected = client.post(
                f"/api/v1/collectors/{collector['id']}/sinks",
                headers={"Idempotency-Key": f"sink-invalid-url-{index:010d}"},
                json={"url": url},
            )
            assert rejected.status_code == 400, url
            assert rejected.json()["code"] == "INVALID_URL"

        disabled = client.put(
            f"/api/v1/collectors/{collector['id']}/sinks/{sink['id']}",
            headers={"Idempotency-Key": "sink-update-00000001"},
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["version"] == 2
        assert disabled.json()["enabled"] is False
        assert disabled.json()["credentialConfigured"] is True, "omitted secret keeps the stored credential"

        rekeyed = client.put(
            f"/api/v1/collectors/{collector['id']}/sinks/{sink['id']}",
            headers={"Idempotency-Key": "sink-update-00000002"},
            json={"secret": "fake-sink-secret-2"},
        )
        assert rekeyed.status_code == 200
        assert rekeyed.json()["version"] == 3
        assert rekeyed.json()["credentialConfigured"] is True
        assert "fake-sink-secret-2" not in rekeyed.text
        cipher = CredentialCipher(app_module.settings.credential_encryption_key_path)
        assert store.get_sink(sink["id"], cipher=cipher)["secretConfigured"] is True

        unknown = client.put(
            f"/api/v1/collectors/{collector['id']}/sinks/sink_missing",
            headers={"Idempotency-Key": "sink-update-00000003"},
            json={"enabled": True},
        )
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "SINK_NOT_FOUND"

        listed = client.get(f"/api/v1/collectors/{collector['id']}/sinks")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["items"]] == [sink["id"]]
        assert all("secret" not in row and "secretConfigured" not in row for row in listed.json()["items"])

        missing_collector = client.get("/api/v1/collectors/collector_missing/sinks")
        assert missing_collector.status_code == 404
        assert missing_collector.json()["code"] == "COLLECTOR_NOT_FOUND"

        deleted = client.delete(
            f"/api/v1/collectors/{collector['id']}/sinks/{sink['id']}",
            headers={"Idempotency-Key": "sink-delete-00000001"},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/collectors/{collector['id']}/sinks").json()["items"] == []

        replayed_delete = client.delete(
            f"/api/v1/collectors/{collector['id']}/sinks/{sink['id']}",
            headers={"Idempotency-Key": "sink-delete-00000001"},
        )
        assert replayed_delete.status_code == 204
        assert replayed_delete.headers["Idempotency-Replayed"] == "true"

        unknown_delete = client.delete(
            f"/api/v1/collectors/{collector['id']}/sinks/sink_missing",
            headers={"Idempotency-Key": "sink-delete-00000002"},
        )
        assert unknown_delete.status_code == 404
        assert unknown_delete.json()["code"] == "SINK_NOT_FOUND"


def test_sink_test_endpoint_enqueues_synthetic_delivery(tmp_path: Path) -> None:
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
        created = client.post(
            f"/api/v1/collectors/{collector['id']}/sinks",
            headers={"Idempotency-Key": "sink-create-000000001"},
            json={"url": "https://hooks.example.com/extrio", "secret": "fake-sink-secret-1"},
        )
        sink = created.json()

        accepted = client.post(
            f"/api/v1/collectors/{collector['id']}/sinks/{sink['id']}/test",
            headers={"Idempotency-Key": "sink-test-000000001"},
        )
        assert accepted.status_code == 202, accepted.json()
        delivery = accepted.json()
        assert delivery["kind"] == "test"
        assert delivery["itemEventId"].startswith("test_")
        assert delivery["status"] == "pending"
        assert delivery["sinkId"] == sink["id"]
        assert delivery["sinkVersionId"] == f"{sink['id']}#v1"
        assert accepted.headers["Location"] == f"/api/v1/deliveries/{delivery['id']}"

        replay = client.post(
            f"/api/v1/collectors/{collector['id']}/sinks/{sink['id']}/test",
            headers={"Idempotency-Key": "sink-test-000000001"},
        )
        assert replay.status_code == 202
        assert replay.json()["id"] == delivery["id"]

        listed = client.get(f"/api/v1/collectors/{collector['id']}/deliveries")
        assert listed.status_code == 200
        rows = listed.json()["items"]
        assert [row["id"] for row in rows] == [delivery["id"]]
        assert rows[0]["kind"] == "test"
        assert rows[0]["latestAttempt"] is None

        detail = client.get(f"/api/v1/deliveries/{delivery['id']}")
        assert detail.status_code == 200
        assert detail.json()["attempts"] == []

        missing_sink = client.post(
            f"/api/v1/collectors/{collector['id']}/sinks/sink_missing/test",
            headers={"Idempotency-Key": "sink-test-000000002"},
        )
        assert missing_sink.status_code == 404
        assert missing_sink.json()["code"] == "SINK_NOT_FOUND"


def test_delivery_detail_and_redeliver_endpoints(tmp_path: Path) -> None:
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
        cipher = CredentialCipher(tmp_path / "keys" / "cipher.key")
        sink = store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/extrio", secret="fake-sink-secret")
        delivery = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_1")
        store.mark_delivery_delivered(delivery["id"])

        redelivered = client.post(
            f"/api/v1/deliveries/{delivery['id']}/redeliver",
            headers={"Idempotency-Key": "redeliver-0000000001"},
        )
        assert redelivered.status_code == 200, redelivered.json()
        body = redelivered.json()
        assert body["id"] == delivery["id"]
        assert body["status"] == "pending"
        assert body["redeliveryCount"] == 1

        unknown_redeliver = client.post(
            "/api/v1/deliveries/delivery_missing/redeliver",
            headers={"Idempotency-Key": "redeliver-0000000002"},
        )
        assert unknown_redeliver.status_code == 404
        assert unknown_redeliver.json()["code"] == "DELIVERY_NOT_FOUND"

        unknown_detail = client.get("/api/v1/deliveries/delivery_missing")
        assert unknown_detail.status_code == 404
        assert unknown_detail.json()["code"] == "DELIVERY_NOT_FOUND"

        # A delivery with an active worker lease cannot be redelivered.
        claimed = store.claim_due_deliveries(1, now=datetime.now(UTC).astimezone(UTC) + timedelta(seconds=10))
        assert [row["id"] for row in claimed] == [delivery["id"]]
        conflict = client.post(
            f"/api/v1/deliveries/{delivery['id']}/redeliver",
            headers={"Idempotency-Key": "redeliver-0000000003"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "DELIVERY_IN_FLIGHT"

        # Attempt history appears in the detail view and as the latest attempt summary.
        store.record_delivery_attempt(delivery["id"], status_code=200)
        store.mark_delivery_delivered(delivery["id"])
        detail = client.get(f"/api/v1/deliveries/{delivery['id']}")
        attempts = detail.json()["attempts"]
        assert [attempt["attemptNo"] for attempt in attempts] == [1]
        assert attempts[0]["statusCode"] == 200
        listed = client.get(f"/api/v1/collectors/{collector['id']}/deliveries")
        assert listed.json()["items"][0]["latestAttempt"]["attemptNo"] == 1


def test_output_loop_endpoints_require_authentication(tmp_path: Path) -> None:
    original_store = app_module.store
    original_settings = app_module.settings
    app_module.store = output_store(tmp_path)
    app_module.store.initialize()
    app_module.settings = original_settings.model_copy(
        update={"auth_enabled": True, "auth_cookie_secure": False, "seed_demo": False},
    )
    try:
        with TestClient(app_module.app) as client:
            guarded = [
                client.get("/api/v1/items"),
                client.get("/api/v1/items/export?format=csv"),
                client.get("/api/v1/collectors/collector_x/sinks"),
                client.post("/api/v1/collectors/collector_x/sinks", json={"url": "https://hooks.example.com/x"}),
                client.put("/api/v1/collectors/collector_x/sinks/sink_x", json={"enabled": False}),
                client.delete("/api/v1/collectors/collector_x/sinks/sink_x"),
                client.post("/api/v1/collectors/collector_x/sinks/sink_x/test"),
                client.get("/api/v1/collectors/collector_x/deliveries"),
                client.get("/api/v1/deliveries/delivery_x"),
                client.post("/api/v1/deliveries/delivery_x/redeliver"),
            ]
            assert all(response.status_code == 401 for response in guarded)
            assert client.get("/api/v1/items").json()["code"] == "AUTH_REQUIRED"
    finally:
        app_module.store = original_store
        app_module.settings = original_settings
