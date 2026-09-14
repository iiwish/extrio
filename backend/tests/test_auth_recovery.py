from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from test_collection_versions import client as client

import extrio.app as app_module
from extrio.store import AuthSetupComplete


def test_first_admin_setup_is_single_winner_across_connections(client):
    barrier = Barrier(8)

    def setup(index):
        barrier.wait()
        try:
            app_module.store.create_first_auth_user(username=f"operator{index}", display_name="Operator", password_hash="fixture")
            return True
        except AuthSetupComplete:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(setup, range(8))) == 1


def test_last_admin_protection_is_atomic_in_store(client):
    store = app_module.store
    users = [
        store.create_user(username=f"operator{index}", display_name="Operator", password_hash="fixture", role="administrator")
        for index in range(2)
    ]
    barrier = Barrier(2)

    def disable(user):
        barrier.wait()
        try:
            store.update_user(user["id"], enabled=False)
            return True
        except ValueError as exc:
            assert str(exc) == "LAST_ADMINISTRATOR"
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(disable, users)) == 1
    assert store.count_active_administrators() == 1


def test_expired_session_is_rejected_and_password_reset_revokes_sessions(client):
    store = app_module.store
    user = store.create_user(username="operator", display_name="Operator", password_hash="fixture", role="engineer")
    store.create_auth_session(token_hash="expired", user_id=user["id"], expires_at="2000-01-01T00:00:00Z")
    assert store.get_auth_session("expired") is None
    store.create_auth_session(token_hash="active", user_id=user["id"], expires_at="2099-01-01T00:00:00Z")
    assert store.get_auth_session("active")
    store.update_user_password(user["id"], "replacement")
    assert store.get_auth_session("active") is None


def test_password_reset_wins_over_an_inflight_old_password_login(client, monkeypatch):
    from extrio.auth import hash_password

    monkeypatch.setattr(app_module, "settings", app_module.settings.model_copy(update={"auth_enabled": True}))
    user = app_module.store.create_user(
        username="race-login", display_name="Operator", password_hash=hash_password("old-password"), role="engineer"
    )
    verify = app_module.verify_password

    def resetting_verify(password, encoded):
        valid = verify(password, encoded)
        app_module.store.update_user_password(user["id"], hash_password("new-password"))
        return valid

    monkeypatch.setattr(app_module, "verify_password", resetting_verify)
    response = client.post("/api/v1/auth/login", json={"username": "race-login", "password": "old-password"})
    assert response.status_code == 401
    with app_module.store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM auth_sessions").fetchone()["n"] == 0


def test_export_and_cancellation_authorization_is_server_side(client, monkeypatch):
    from extrio.auth import session_token_hash

    monkeypatch.setattr(app_module, "settings", app_module.settings.model_copy(update={"auth_enabled": True}))
    assert client.get("/api/v1/items/export?format=csv").status_code == 401
    assert client.get("/api/v1/runs/run_missing/evidence").status_code == 401
    assert client.post("/api/v1/operations/op_missing/cancel").status_code == 401
    viewer = app_module.store.create_user(username="viewer", display_name="Viewer", password_hash="fixture", role="viewer")
    app_module.store.create_auth_session(
        token_hash=session_token_hash("viewer-token"), user_id=viewer["id"], expires_at="2099-01-01T00:00:00Z"
    )
    client.cookies.set(app_module.settings.auth_cookie_name, "viewer-token")
    assert client.get("/api/v1/items/export?format=csv").status_code == 200
    denied = client.post("/api/v1/operations/op_missing/cancel", headers={"Idempotency-Key": "unauthorized-cancel"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"


def test_demo_robots_is_public_without_exposing_control_plane(monkeypatch):
    from urllib.robotparser import RobotFileParser

    from fastapi.testclient import TestClient

    import extrio.app as app

    monkeypatch.setattr(app, "settings", app.settings.model_copy(update={"auth_enabled": True}))
    client = TestClient(app.app, raise_server_exceptions=False)
    try:
        response = client.get("/robots.txt")
        assert response.status_code == 200
        robots = RobotFileParser()
        robots.parse(response.text.splitlines())
        assert robots.can_fetch("Extrio", "http://testserver/demo/tenders")
        assert not robots.can_fetch("Extrio", "http://testserver/api/v1/collectors")
        assert client.get("/api/v1/collectors").status_code == 401
    finally:
        client.close()
