"""v0.6 platform settings: UI-configurable anonymous-HTTP collection policy.

Covers the scalar platform-setting KV (``platform_setting_values``), the
effective-flag resolver, migration 002 (fresh + v0.5 upgrade path), and the
``/api/v1/settings/platform`` endpoint contract. The credential-HTTPS hard line
stays with ``normalize_source_url`` and is asserted in ``test_security.py``.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.auth import hash_password, reset_login_limits
from extrio.config import get_settings
from extrio.store import Store


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "settings.db")
    store.initialize()
    return store


def test_platform_setting_value_roundtrip(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.get_platform_setting_value("allowAnonymousHttp") == "true"
    assert store.get_platform_setting_value("never_configured") is None

    detail = store.get_platform_setting_value_detail("allowAnonymousHttp")
    assert detail is not None
    assert detail["key"] == "allowAnonymousHttp"
    assert detail["value"] == "true"
    assert detail["updatedBy"] is None
    assert str(detail["updatedAt"]).endswith("Z")

    saved = store.set_platform_setting_value("allowAnonymousHttp", "false", updated_by="user_root")
    assert saved == {
        "key": "allowAnonymousHttp",
        "value": "false",
        "updatedBy": "user_root",
        "updatedAt": saved["updatedAt"],
    }
    reread = store.get_platform_setting_value_detail("allowAnonymousHttp")
    assert reread == saved


def test_effective_flag_defaults_true_and_follows_the_row(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.effective_allow_http_public() is True

    store.set_platform_setting_value("allowAnonymousHttp", "false", updated_by="user_root")
    assert store.effective_allow_http_public() is False

    with store.transaction() as connection:
        connection.execute("DELETE FROM platform_setting_values WHERE key='allowAnonymousHttp'")
    assert store.get_platform_setting_value("allowAnonymousHttp") is None
    assert store.effective_allow_http_public() is True


def test_effective_flag_falls_back_to_config_only_while_row_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    with store.transaction() as connection:
        connection.execute("DELETE FROM platform_setting_values WHERE key='allowAnonymousHttp'")

    monkeypatch.setattr(get_settings(), "allow_http_public", False)
    assert store.effective_allow_http_public() is False

    store.set_platform_setting_value("allowAnonymousHttp", "true", updated_by="user_root")
    assert store.effective_allow_http_public() is True


def test_reinitialization_does_not_reset_the_seeded_flag(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.set_platform_setting_value("allowAnonymousHttp", "false", updated_by="user_root")

    store.initialize()

    assert store.get_platform_setting_value("allowAnonymousHttp") == "false"


def test_migration_002_applies_to_v05_database_without_the_row(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    with store.transaction() as connection:
        connection.execute("DROP TABLE platform_setting_values")
        connection.execute("DELETE FROM schema_migrations WHERE id='002_platform_settings'")

    store.initialize()

    with store.connect() as connection:
        applied = [str(row["id"]) for row in connection.execute("SELECT id FROM schema_migrations").fetchall()]
    assert applied == ["000_baseline", "001_user_accounts", "002_platform_settings"]
    assert store.get_platform_setting_value("allowAnonymousHttp") == "true"


def test_api_anonymous_http_allowed_by_default_then_disallowed_via_settings(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path)
    try:
        with TestClient(app_module.app) as client:
            view = client.get("/api/v1/settings/platform")
            assert view.status_code == 200
            assert view.json()["allowAnonymousHttp"] is True
            assert view.json()["updatedBy"] is None

            created = client.post(
                "/api/v1/collectors",
                headers={"Idempotency-Key": "anon-http-default-00001"},
                json={"name": "Source", "intent": "Collect", "sourceUrl": "http://example.com/list"},
            )
            assert created.status_code == 201, created.json()
            assert created.json()["sourceUrl"] == "http://example.com/list"

            disabled = client.put(
                "/api/v1/settings/platform",
                headers={"Idempotency-Key": "platform-setting-off-0001"},
                json={"allowAnonymousHttp": False},
            )
            assert disabled.status_code == 200, disabled.json()
            disabled_body = disabled.json()
            assert disabled_body["allowAnonymousHttp"] is False
            assert disabled_body["updatedBy"] == "user_local_development"
            assert str(disabled_body["updatedAt"]).endswith("Z")

            rejected = client.post(
                "/api/v1/collectors",
                headers={"Idempotency-Key": "anon-http-blocked-00001"},
                json={"name": "Source", "intent": "Collect", "sourceUrl": "http://example.com/blocked"},
            )
            assert rejected.status_code == 422
            assert rejected.json()["code"] == "HTTPS_REQUIRED"
            assert rejected.json()["message"] == (
                "匿名 HTTP 来源默认已被允许；如被关闭，请由管理员在 设置 → 采集策略 中开启，或改用 HTTPS"
            )

            https_created = client.post(
                "/api/v1/collectors",
                headers={"Idempotency-Key": "https-still-works-0001"},
                json={"name": "Secure", "intent": "Collect", "sourceUrl": "https://example.org/list"},
            )
            assert https_created.status_code == 201

            view = client.get("/api/v1/settings/platform")
            assert view.json()["allowAnonymousHttp"] is False
            assert view.json()["updatedBy"] == "user_local_development"

            replayed = client.put(
                "/api/v1/settings/platform",
                headers={"Idempotency-Key": "platform-setting-off-0001"},
                json={"allowAnonymousHttp": False},
            )
            assert replayed.status_code == 200
            assert replayed.headers["Idempotency-Replayed"] == "true"
    finally:
        app_module.store = original


def test_api_batch_rejects_anonymous_http_per_url_when_disabled(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path)
    try:
        with TestClient(app_module.app) as client:
            assert (
                client.put(
                    "/api/v1/settings/platform",
                    headers={"Idempotency-Key": "platform-setting-off-0002"},
                    json={"allowAnonymousHttp": False},
                )
            ).status_code == 200

            response = client.post(
                "/api/v1/collectors/batch",
                headers={"Idempotency-Key": "batch-anon-http-0000001"},
                json={
                    "collectionName": "混合批次",
                    "intent": "采集公开招标公告",
                    "sourceUrls": [
                        "http://a.example.gov.cn/notices",
                        "https://b.example.gov.cn/notices",
                    ],
                },
            )
            assert response.status_code == 200, response.json()
            results = response.json()["results"]
            assert results[0]["status"] == "rejected"
            assert results[0]["error"]["code"] == "HTTPS_REQUIRED"
            assert "设置 → 采集策略" in results[0]["error"]["message"]
            assert results[1]["status"] == "created"
    finally:
        app_module.store = original


def test_api_platform_setting_rejects_non_bool(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path)
    try:
        with TestClient(app_module.app) as client:
            for bad_value in ("yes", 1, None):
                rejected = client.put(
                    "/api/v1/settings/platform",
                    headers={"Idempotency-Key": f"platform-setting-bad-{bad_value}"},
                    json={"allowAnonymousHttp": bad_value},
                )
                assert rejected.status_code == 422
                assert rejected.json()["code"] == "VALIDATION_FAILED"
                assert rejected.json()["pointer"] == "/allowAnonymousHttp"
            assert client.get("/api/v1/settings/platform").json()["allowAnonymousHttp"] is True
    finally:
        app_module.store = original


def test_api_platform_setting_put_requires_administrator(tmp_path: Path) -> None:
    original_store = app_module.store
    original_settings = app_module.settings
    store = make_store(tmp_path)
    app_module.store = store
    app_module.settings = original_settings.model_copy(
        update={"auth_enabled": True, "auth_login_limit": "10/minute", "seed_demo": False}
    )
    store.create_first_auth_user(username="root", display_name="Root", password_hash=hash_password("root-password-1"))
    store.create_user(
        username="engineer",
        password_hash=hash_password("engineer-password-1"),
        role="engineer",
        display_name="Engineer",
    )
    try:
        admin = TestClient(app_module.app)
        assert admin.post("/api/v1/auth/login", json={"username": "root", "password": "root-password-1"}).status_code == 200
        engineer = TestClient(app_module.app)
        assert (
            engineer.post("/api/v1/auth/login", json={"username": "engineer", "password": "engineer-password-1"}).status_code
            == 200
        )

        assert engineer.get("/api/v1/settings/platform").status_code == 200
        denied = engineer.put(
            "/api/v1/settings/platform",
            headers={"Idempotency-Key": "engineer-flag-blocked-01"},
            json={"allowAnonymousHttp": False},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "FORBIDDEN"

        allowed = admin.put(
            "/api/v1/settings/platform",
            headers={"Idempotency-Key": "admin-flag-allowed-001"},
            json={"allowAnonymousHttp": False},
        )
        assert allowed.status_code == 200
        assert allowed.json()["updatedBy"] == store.get_auth_credentials("root")["id"]

        anonymous = TestClient(app_module.app)
        assert anonymous.get("/api/v1/settings/platform").status_code == 401
    finally:
        app_module.store = original_store
        app_module.settings = original_settings
        reset_login_limits()
