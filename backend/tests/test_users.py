"""v0.4 multi-user accounts: role enforcement, users CRUD, and account lifecycle."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.auth import hash_password, reset_login_limits
from extrio.harvest import build_candidate
from extrio.store import Store, UsernameTaken

PASSWORDS = {
    "root": "root-password-1",
    "engineer": "engineer-password-1",
    "reviewer": "reviewer-password-1",
    "viewer": "viewer-password-1",
}


@pytest.fixture
def user_store(tmp_path: Path) -> Store:
    original_store = app_module.store
    original_settings = app_module.settings
    store = Store(tmp_path / "users.db")
    store.initialize()
    app_module.store = store
    app_module.settings = original_settings.model_copy(
        update={
            "auth_enabled": True,
            "auth_cookie_secure": False,
            "auth_login_limit": "10/minute",
            "seed_demo": False,
        }
    )
    store.create_first_auth_user(username="root", display_name="Root", password_hash=hash_password(PASSWORDS["root"]))
    yield store
    app_module.store = original_store
    app_module.settings = original_settings
    reset_login_limits()


def make_user(store: Store, username: str, role: str) -> dict:
    return store.create_user(
        username=username,
        password_hash=hash_password(PASSWORDS[username]),
        role=role,
        display_name=username.title(),
    )


def login_client(username: str, password: str) -> TestClient:
    client = TestClient(app_module.app)
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.json()
    return client


def admin_client(store: Store) -> TestClient:
    return login_client("root", PASSWORDS["root"])


def ready_review_collector(store: Store) -> str:
    collector = store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
    list_html = '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">A</a></li></ul>'
    detail_html = '<h1 class="notice-title">A</h1><div class="meta"><span data-field="buyer">B</span></div>'
    collector.update(
        status="ready_review",
        candidate=build_candidate(collector, app_module.contracts, list_html, [("https://example.com/detail/1", detail_html)]),
    )
    store.save_collector(collector)
    return collector["id"]


def test_store_user_views_and_case_insensitive_duplicate(user_store: Store) -> None:
    engineer = make_user(user_store, "engineer", "engineer")
    assert set(engineer) == {"id", "username", "displayName", "role", "enabled", "createdAt", "updatedAt"}
    assert engineer["enabled"] is True and "passwordHash" not in engineer
    with pytest.raises(UsernameTaken) as taken:
        user_store.create_user(
            username="ENGINEER",
            password_hash=hash_password(PASSWORDS["viewer"]),
            role="viewer",
            display_name="Dup",
        )
    assert taken.value.code == "USERNAME_TAKEN"
    assert [user["username"] for user in user_store.list_users()] == ["root", "engineer"]


def test_store_update_user_password_and_active_administrator_count(user_store: Store) -> None:
    engineer = make_user(user_store, "engineer", "engineer")
    assert user_store.count_active_administrators() == 1
    user_store.update_user(engineer["id"], role="administrator")
    assert user_store.count_active_administrators() == 2
    user_store.update_user(engineer["id"], enabled=False)
    assert user_store.count_active_administrators() == 1
    assert user_store.get_user(engineer["id"])["enabled"] is False
    with pytest.raises(KeyError):
        user_store.update_user("user_missing", role="viewer")

    user_store.update_user_password(engineer["id"], hash_password("rotated-password-1"))
    credentials = user_store.get_auth_credentials("engineer")
    assert credentials is not None and credentials["enabled"] is False
    assert credentials["passwordHash"].startswith("$argon2")


def test_role_matrix_on_collector_and_settings_mutations(user_store: Store) -> None:
    make_user(user_store, "engineer", "engineer")
    make_user(user_store, "reviewer", "reviewer")
    make_user(user_store, "viewer", "viewer")
    collector_id = ready_review_collector(user_store)
    engineer = login_client("engineer", PASSWORDS["engineer"])
    reviewer = login_client("reviewer", PASSWORDS["reviewer"])
    viewer = login_client("viewer", PASSWORDS["viewer"])

    rejected = reviewer.post(
        "/api/v1/collectors",
        headers={"Idempotency-Key": "reviewer-create-blocked-0001"},
        json={"name": "Source", "intent": "Collect", "sourceUrl": "https://example.org/list"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "FORBIDDEN"
    assert "engineer" in rejected.json()["message"] and "administrator" in rejected.json()["message"]

    created = engineer.post(
        "/api/v1/collectors",
        headers={"Idempotency-Key": "engineer-create-allowed-0001"},
        json={"name": "Source", "intent": "Collect", "sourceUrl": "https://example.org/list"},
    )
    assert created.status_code == 201, created.json()

    assert viewer.post(
        "/api/v1/collectors",
        headers={"Idempotency-Key": "viewer-create-blocked-0001"},
        json={"name": "Source", "intent": "Collect", "sourceUrl": "https://example.net/list"},
    ).status_code == 403

    publish_denied = engineer.post(
        f"/api/v1/collectors/{collector_id}/publish",
        headers={"Idempotency-Key": "engineer-publish-blocked-001"},
        json={"reviewDecisions": {}},
    )
    assert publish_denied.status_code == 403
    assert publish_denied.json()["code"] == "FORBIDDEN"

    publish_allowed = reviewer.post(
        f"/api/v1/collectors/{collector_id}/publish",
        headers={"Idempotency-Key": "reviewer-publish-gate-0001"},
        json={"reviewDecisions": {}},
    )
    assert publish_allowed.status_code == 409
    assert publish_allowed.json()["code"] == "REVIEW_DECISION_INVALID"

    patched = engineer.patch(
        f"/api/v1/collectors/{collector_id}",
        headers={"Idempotency-Key": "engineer-patch-gate-00000001"},
        json={"name": "Source", "intent": "Collect", "sourceUrl": "https://example.com/list"},
    )
    assert patched.status_code == 200, patched.json()
    assert reviewer.patch(
        f"/api/v1/collectors/{collector_id}",
        headers={"Idempotency-Key": "reviewer-patch-blocked-0001"},
        json={"name": "Source", "intent": "Collect", "sourceUrl": "https://example.com/list"},
    ).status_code == 403

    for role_client, tag in ((engineer, "engineer"), (reviewer, "reviewer"), (viewer, "viewer")):
        assert role_client.put(
            "/api/v1/settings/models",
            headers={"Idempotency-Key": f"settings-put-blocked-{tag}-0001"},
            json={"providers": [], "models": [], "defaultModelId": None},
        ).status_code == 403
        assert role_client.get("/api/v1/users").status_code == 403
        assert role_client.post(
            "/api/v1/users",
            headers={"Idempotency-Key": f"users-create-blocked-{tag}-001"},
            json={"username": "intruder", "password": "intruder-pass-1", "role": "administrator"},
        ).status_code == 403

    assert viewer.get("/api/v1/items").status_code == 200
    assert viewer.get("/api/v1/items/export?format=jsonl").status_code == 200
    assert engineer.get("/api/v1/items/export?format=jsonl").status_code == 200
    assert viewer.get("/api/v1/collectors").status_code == 200
    assert viewer.get("/api/v1/runs").status_code == 200


def test_users_crud_happy_path_and_validation(user_store: Store) -> None:
    client = admin_client(user_store)
    created = client.post(
        "/api/v1/users",
        headers={"Idempotency-Key": "users-create-engineer-00001"},
        json={"username": "engineer", "password": "engineer-password-1", "role": "engineer", "displayName": "采集工程师"},
    )
    assert created.status_code == 201, created.json()
    user = created.json()
    assert user["username"] == "engineer"
    assert user["role"] == "engineer"
    assert user["displayName"] == "采集工程师"
    assert user["enabled"] is True
    assert "password" not in user and "passwordHash" not in user
    assert created.headers["Location"] == f"/api/v1/users/{user['id']}"

    duplicate = client.post(
        "/api/v1/users",
        headers={"Idempotency-Key": "users-create-duplicate-00001"},
        json={"username": "ENGINEER", "password": "engineer-password-1", "role": "engineer"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "USERNAME_TAKEN"

    for key, payload in {
        "bad-username": {"username": "x", "password": "engineer-password-1", "role": "engineer"},
        "bad-password": {"username": "someone", "password": "short", "role": "engineer"},
        "bad-role": {"username": "someone", "password": "engineer-password-1", "role": "owner"},
    }.items():
        invalid = client.post(
            "/api/v1/users",
            headers={"Idempotency-Key": f"users-create-invalid-{key}"},
            json=payload,
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "VALIDATION_FAILED"

    listing = client.get("/api/v1/users")
    assert listing.status_code == 200
    assert [item["username"] for item in listing.json()["items"]] == ["root", "engineer"]
    assert all("passwordHash" not in item and "password" not in item for item in listing.json()["items"])

    renamed = client.patch(
        f"/api/v1/users/{user['id']}",
        headers={"Idempotency-Key": "users-patch-display-00000001"},
        json={"displayName": "改名后的工程师"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["displayName"] == "改名后的工程师"

    rotated = client.patch(
        f"/api/v1/users/{user['id']}",
        headers={"Idempotency-Key": "users-patch-password-000001"},
        json={"password": "rotated-password-9"},
    )
    assert rotated.status_code == 200
    engineer_login = login_client("engineer", "rotated-password-9")
    assert engineer_login.get("/api/v1/auth/state").json()["user"]["role"] == "engineer"

    missing = client.patch(
        "/api/v1/users/user_missing",
        headers={"Idempotency-Key": "users-patch-missing-0000001"},
        json={"displayName": "Nobody"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "USER_NOT_FOUND"


def test_last_administrator_protection(user_store: Store) -> None:
    client = admin_client(user_store)
    root_id = client.get("/api/v1/auth/state").json()["user"]["id"]

    demoted = client.patch(
        f"/api/v1/users/{root_id}",
        headers={"Idempotency-Key": "users-demote-last-admin-0001"},
        json={"role": "engineer"},
    )
    assert demoted.status_code == 409
    assert demoted.json()["code"] == "LAST_ADMINISTRATOR"

    renamed = client.patch(
        f"/api/v1/users/{root_id}",
        headers={"Idempotency-Key": "users-rename-last-admin-0001"},
        json={"displayName": "仍然是管理员"},
    )
    assert renamed.status_code == 200

    peer = client.post(
        "/api/v1/users",
        headers={"Idempotency-Key": "users-create-second-admin-001"},
        json={"username": "root2", "password": "second-admin-pass", "role": "administrator"},
    )
    assert peer.status_code == 201
    demote_peer = client.patch(
        f"/api/v1/users/{peer.json()['id']}",
        headers={"Idempotency-Key": "users-demote-second-admin-01"},
        json={"role": "viewer"},
    )
    assert demote_peer.status_code == 200
    disable_peer = client.patch(
        f"/api/v1/users/{peer.json()['id']}",
        headers={"Idempotency-Key": "users-disable-second-admin-01"},
        json={"enabled": False},
    )
    assert disable_peer.status_code == 200

    now_blocked = client.patch(
        f"/api/v1/users/{root_id}",
        headers={"Idempotency-Key": "users-demote-last-admin-0002"},
        json={"role": "engineer"},
    )
    assert now_blocked.status_code == 409
    assert now_blocked.json()["code"] == "LAST_ADMINISTRATOR"


def test_self_disable_protection_and_self_service(user_store: Store) -> None:
    client = admin_client(user_store)
    root_id = client.get("/api/v1/auth/state").json()["user"]["id"]

    blocked = client.patch(
        f"/api/v1/users/{root_id}",
        headers={"Idempotency-Key": "users-self-disable-00000001"},
        json={"enabled": False},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "SELF_DISABLE"

    self_service = client.patch(
        f"/api/v1/users/{root_id}",
        headers={"Idempotency-Key": "users-self-service-0000001"},
        json={"displayName": "自改显示名", "password": "root-password-2"},
    )
    assert self_service.status_code == 200
    assert login_client("root", "root-password-2").get("/api/v1/auth/state").json()["user"]["id"] == root_id


def test_disabled_user_login_is_generic_failure(user_store: Store) -> None:
    admin = admin_client(user_store)
    engineer = make_user(user_store, "engineer", "engineer")
    disabled = admin.patch(
        f"/api/v1/users/{engineer['id']}",
        headers={"Idempotency-Key": "users-disable-engineer-00001"},
        json={"enabled": False},
    )
    assert disabled.status_code == 200

    correct = TestClient(app_module.app).post(
        "/api/v1/auth/login",
        json={"username": "engineer", "password": PASSWORDS["engineer"]},
    )
    unknown = TestClient(app_module.app).post(
        "/api/v1/auth/login",
        json={"username": "ghost", "password": "whatever-password"},
    )
    wrong = TestClient(app_module.app).post(
        "/api/v1/auth/login",
        json={"username": "engineer", "password": "wrong-password"},
    )
    assert correct.status_code == unknown.status_code == wrong.status_code == 401
    assert correct.json()["code"] == unknown.json()["code"] == wrong.json()["code"] == "INVALID_CREDENTIALS"
    assert correct.json()["message"] == unknown.json()["message"] == wrong.json()["message"]


def test_disabled_user_session_is_rejected(user_store: Store) -> None:
    admin = admin_client(user_store)
    make_user(user_store, "engineer", "engineer")
    engineer = login_client("engineer", PASSWORDS["engineer"])
    assert engineer.get("/api/v1/collectors").status_code == 200

    engineer_id = engineer.get("/api/v1/auth/state").json()["user"]["id"]
    disabled = admin.patch(
        f"/api/v1/users/{engineer_id}",
        headers={"Idempotency-Key": "users-disable-live-session-1"},
        json={"enabled": False},
    )
    assert disabled.status_code == 200

    assert engineer.get("/api/v1/collectors").status_code == 401
    assert engineer.get("/api/v1/auth/state").json()["authenticated"] is False
    assert TestClient(app_module.app).get("/api/v1/collectors").status_code == 401


def test_auth_state_exposes_role_and_display_name(user_store: Store) -> None:
    client = admin_client(user_store)
    state = client.get("/api/v1/auth/state").json()
    assert state["authenticated"] is True
    assert state["user"]["role"] == "administrator"
    assert state["user"]["displayName"] == "Root"


def test_auth_disabled_bypasses_role_guards(tmp_path: Path) -> None:
    original_store = app_module.store
    app_module.store = Store(tmp_path / "bypass.db")
    app_module.store.initialize()
    try:
        with TestClient(app_module.app) as client:
            assert app_module.settings.auth_enabled is False
            created = client.post(
                "/api/v1/users",
                headers={"Idempotency-Key": "users-bypass-create-000001"},
                json={"username": "engineer", "password": "engineer-password-1", "role": "engineer"},
            )
            assert created.status_code == 201, created.json()
            assert client.get("/api/v1/users").status_code == 200
            assert client.put(
                "/api/v1/settings/models",
                headers={"Idempotency-Key": "settings-bypass-put-0000001"},
                json={"providers": [], "models": [], "defaultModelId": None},
            ).status_code == 200
    finally:
        app_module.store = original_store
