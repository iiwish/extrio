from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.credentials import CredentialCipher
from extrio.metrics import render_metrics
from extrio.store import Store


def swap_app_store(tmp_path: Path, **setting_overrides: object) -> tuple[Store, object]:
    """Point the app at a fresh store and settings copy (test_auth.py pattern)."""

    original_store = app_module.store
    original_settings = app_module.settings
    app_module.store = Store(tmp_path / "metrics.db")
    app_module.store.initialize()
    app_module.settings = original_settings.model_copy(update={"seed_demo": False, **setting_overrides})
    return original_store, original_settings


def restore_app_store(original_store: Store, original_settings: object) -> None:
    app_module.store = original_store
    app_module.settings = original_settings


def make_run(run_id: str, collector_id: str, status: str) -> dict:
    return {
        "id": run_id,
        "collectorId": collector_id,
        "collectorName": "Demo",
        "status": status,
        "items": [],
    }


def seed_scrape_state(store: Store, tmp_path: Path) -> None:
    collector = store.create_collector("Demo", "Collect notices", "https://example.com/list", "example.com")
    store.save_run(make_run("run_metrics_s1", collector["id"], "succeeded"))
    store.save_run(make_run("run_metrics_s2", collector["id"], "succeeded"))
    store.save_run(make_run("run_metrics_f1", collector["id"], "failed"))
    store.save_items(
        "run_metrics_s1",
        [
            {"id": "item_metrics_a", "decision": "accepted"},
            {"id": "item_metrics_b", "decision": "accepted"},
            {"id": "item_metrics_c", "decision": "rejected"},
        ],
    )
    cipher = CredentialCipher(tmp_path / "keys" / "metrics-cipher.key")
    enabled_sink = store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/on")
    store.create_sink(collector["id"], cipher=cipher, url="https://hooks.example.com/off", enabled=False)
    store.enqueue_delivery(collector_id=collector["id"], sink_id=enabled_sink["id"], item_event_id="evt_metrics_pending")
    delivered = store.enqueue_delivery(
        collector_id=collector["id"], sink_id=enabled_sink["id"], item_event_id="evt_metrics_delivered"
    )
    store.mark_delivery_delivered(delivered["id"])


def test_metrics_disabled_returns_plain_404_not_platform_error(tmp_path: Path) -> None:
    original_store, original_settings = swap_app_store(tmp_path, metrics_enabled=False)
    try:
        with TestClient(app_module.app) as client:
            response = client.get("/metrics")
            assert response.status_code == 404
            assert response.content == b""
            assert "requestId" not in response.text
    finally:
        restore_app_store(original_store, original_settings)


def test_metrics_enabled_renders_prometheus_text_from_seeded_state(tmp_path: Path) -> None:
    original_store, original_settings = swap_app_store(tmp_path, metrics_enabled=True)
    try:
        with TestClient(app_module.app) as client:
            seed_scrape_state(app_module.store, tmp_path)
            response = client.get("/metrics")
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
            body = response.text
            assert body.endswith("\n")
            assert "# HELP extrio_up Whether the Extrio control plane answered this scrape." in body
            assert "# TYPE extrio_up gauge" in body
            assert "extrio_up 1" in body
            assert 'extrio_collectors_total{status="draft"} 1' in body
            assert 'extrio_runs_total{status="failed"} 1' in body
            assert 'extrio_runs_total{status="succeeded"} 2' in body
            assert 'extrio_runs_24h_total{status="failed"} 1' in body
            assert 'extrio_runs_24h_total{status="succeeded"} 2' in body
            assert 'extrio_items_total{decision="accepted"} 2' in body
            assert 'extrio_items_total{decision="rejected"} 1' in body
            assert 'extrio_deliveries_total{status="delivered"} 1' in body
            assert 'extrio_deliveries_total{status="pending"} 1' in body
            assert 'extrio_sinks_total{enabled="false"} 1' in body
            assert 'extrio_sinks_total{enabled="true"} 1' in body
            assert 'extrio_db_dialect_info{dialect="sqlite"} 1' in body
    finally:
        restore_app_store(original_store, original_settings)


def test_metrics_is_reachable_without_authentication(tmp_path: Path) -> None:
    original_store, original_settings = swap_app_store(
        tmp_path,
        metrics_enabled=True,
        auth_enabled=True,
    )
    try:
        with TestClient(app_module.app) as client:
            assert client.get("/api/v1/collectors").status_code == 401
            response = client.get("/metrics")
            assert response.status_code == 200
            assert "extrio_up 1" in response.text
    finally:
        restore_app_store(original_store, original_settings)


@pytest.mark.parametrize("name", ["extrio_up", "extrio_runs_total", "extrio_sinks_total"])
def test_render_metrics_payload_is_deterministic_across_scrapes(tmp_path: Path, name: str) -> None:
    store = Store(tmp_path / "render.db")
    store.initialize()
    seed_scrape_state(store, tmp_path)

    first = render_metrics(store)
    second = render_metrics(store)
    assert first == second
    assert f"# TYPE {name}" in first
