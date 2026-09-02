import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.auth import reset_login_limits, validate_password
from extrio.store import Store


def auth_client(tmp_path: Path):
    original_store = app_module.store
    original_settings = app_module.settings
    app_module.store = Store(tmp_path / "auth.db")
    app_module.store.initialize()
    app_module.settings = original_settings.model_copy(
        update={
            "auth_enabled": True,
            "auth_cookie_secure": False,
            "auth_login_limit": "5/minute",
            "seed_demo": False,
        }
    )
    reset_login_limits()
    return original_store, original_settings


def restore_auth(original_store: Store, original_settings) -> None:
    app_module.store = original_store
    app_module.settings = original_settings
    reset_login_limits()


def test_password_length_boundary() -> None:
    assert validate_password("12345678") == "12345678"
    with pytest.raises(ValueError, match="8 至 256"):
        validate_password("1234567")


def test_first_run_setup_protects_control_plane_and_logout_revokes_session(tmp_path: Path) -> None:
    original_store, original_settings = auth_client(tmp_path)
    try:
        with TestClient(app_module.app) as client:
            state = client.get("/api/v1/auth/state")
            assert state.status_code == 200
            assert state.json() == {
                "authEnabled": True,
                "setupRequired": True,
                "authenticated": False,
                "user": None,
            }
            assert client.get("/api/v1/collectors").status_code == 401
            assert client.get("/gather-spec.schema.json").status_code == 401

            setup = client.post(
                "/api/v1/auth/setup",
                json={"username": "admin", "displayName": "Operator", "password": "correct-horse-battery-staple"},
            )
            assert setup.status_code == 200, setup.json()
            assert setup.json()["user"]["username"] == "admin"
            cookie = setup.headers["set-cookie"]
            assert "HttpOnly" in cookie
            assert "SameSite=strict" in cookie
            assert "Path=/" in cookie
            assert client.get("/api/v1/collectors").status_code == 200

            duplicate = client.post(
                "/api/v1/auth/setup",
                json={"username": "other", "password": "another-valid-password"},
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["code"] == "SETUP_ALREADY_COMPLETED"

            logout = client.post("/api/v1/auth/logout")
            assert logout.status_code == 200
            assert logout.json() == {"authenticated": False}
            assert client.get("/api/v1/collectors").status_code == 401

        with sqlite3.connect(tmp_path / "auth.db") as connection:
            stored = connection.execute("SELECT password_hash FROM auth_users WHERE username='admin'").fetchone()[0]
            assert stored.startswith("$argon2")
            assert "correct-horse-battery-staple" not in stored
            assert connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0
    finally:
        restore_auth(original_store, original_settings)


def test_login_uses_generic_failures_and_rate_limits_attempts(tmp_path: Path) -> None:
    original_store, original_settings = auth_client(tmp_path)
    try:
        with TestClient(app_module.app) as client:
            client.post(
                "/api/v1/auth/setup",
                json={"username": "admin", "password": "correct-horse-battery-staple"},
            )
            client.post("/api/v1/auth/logout")

            unknown = client.post("/api/v1/auth/login", json={"username": "unknown", "password": "wrong"})
            wrong = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
            assert unknown.status_code == wrong.status_code == 401
            assert unknown.json()["message"] == wrong.json()["message"] == "用户名或密码不正确"

            for _ in range(5):
                response = client.post("/api/v1/auth/login", json={"username": "limited", "password": "wrong"})
                assert response.status_code == 401
            limited = client.post("/api/v1/auth/login", json={"username": "limited", "password": "wrong"})
            assert limited.status_code == 429
            assert limited.json()["code"] == "RATE_LIMITED"
            assert limited.headers["Retry-After"] == "60"

            success = client.post(
                "/api/v1/auth/login",
                json={"username": "ADMIN", "password": "correct-horse-battery-staple"},
            )
            assert success.status_code == 200
            assert success.json()["authenticated"] is True
    finally:
        restore_auth(original_store, original_settings)


def test_auth_rejects_cross_origin_mutations(tmp_path: Path) -> None:
    original_store, original_settings = auth_client(tmp_path)
    try:
        with TestClient(app_module.app) as client:
            response = client.post(
                "/api/v1/auth/setup",
                headers={"Origin": "https://attacker.example"},
                json={"username": "admin", "password": "correct-horse-battery-staple"},
            )
            assert response.status_code == 403
            assert response.json()["code"] == "FORBIDDEN"
    finally:
        restore_auth(original_store, original_settings)


def test_auth_can_require_secure_session_cookie(tmp_path: Path) -> None:
    original_store, original_settings = auth_client(tmp_path)
    app_module.settings = app_module.settings.model_copy(update={"auth_cookie_secure": True})
    try:
        with TestClient(app_module.app) as client:
            response = client.post(
                "/api/v1/auth/setup",
                json={"username": "admin", "password": "correct-horse-battery-staple"},
            )
            assert response.status_code == 200
            assert "Secure" in response.headers["set-cookie"]
    finally:
        restore_auth(original_store, original_settings)
