import pytest
from test_collection_migration import command
from test_collection_versions import client  # noqa: F401, F811 - pytest fixture registration

import extrio.app as app_module
from extrio.worker import Worker

FIELDS = [
    {"key": "title", "label": "Title", "type": "string", "required": True, "identity": True, "fingerprint": True, "description": "A title"}
]


def requirement(client):
    response = command(
        client, "POST", "/api/v1/collections", {"name": "Suggestion test", "intent": "Fictional public notices"}, "suggestion-requirement"
    )
    assert response.status_code == 201
    return response.json()


def enqueue(client, col, key="suggestion-start"):
    response = command(client, "POST", f"/api/v1/collections/{col['id']}/field-suggestions", {"revision": col["revision"]}, key)
    assert response.status_code == 202, response.text
    return response.json()


def test_builtin_templates_are_versioned_and_do_not_publish(client):
    col = requirement(client)
    result = client.get("/api/v1/collection-templates")
    assert result.status_code == 200
    templates = result.json()["items"]
    assert len(templates) >= 2
    assert all(template["version"] and template["fields"] for template in templates)
    response = command(
        client,
        "POST",
        f"/api/v1/collections/{col['id']}/apply-template",
        {"revision": col["revision"], "templateId": templates[0]["id"]},
        "apply-template",
    )
    assert response.status_code == 200
    assert response.json()["fieldDraft"]["fields"] == templates[0]["fields"]
    assert response.json()["activeVersionId"] is None
    assert response.json()["revision"] == col["revision"] + 1


@pytest.mark.asyncio
async def test_suggestion_is_persistent_reviewable_and_only_selected_fields_are_saved(client):
    col = requirement(client)
    suggestion = enqueue(client, col)
    assert suggestion["status"] == "queued"
    conflict = command(
        client, "POST", f"/api/v1/collections/{col['id']}/field-suggestions", {"revision": col["revision"]}, "suggestion-duplicate"
    )
    assert conflict.status_code == 409
    from extrio.field_suggestions import claim_suggestion

    job = claim_suggestion(app_module.store)
    assert job is not None

    class Compiler:
        async def suggest_fields(self, snapshot, suggestion_id, attempt):
            assert snapshot["intent"] == col["intent"]
            return FIELDS + [{**FIELDS[0], "key": "summary", "identity": False, "required": False}]

    worker = Worker.__new__(Worker)
    worker.store = app_module.store
    worker.model_compiler = Compiler()
    await worker.process(job)
    restored = client.get(f"/api/v1/collections/{col['id']}/field-suggestions").json()["items"][0]
    assert restored["status"] == "succeeded"
    assert client.get(f"/api/v1/collections/{col['id']}").json().get("fieldDraft") is None
    response = command(
        client,
        "POST",
        f"/api/v1/collections/{col['id']}/field-suggestions/{suggestion['id']}/apply",
        {"revision": col["revision"], "selectedKeys": ["title"]},
        "suggestion-apply",
    )
    assert response.status_code == 200, response.text
    assert response.json()["fieldDraft"]["fields"] == FIELDS
    assert response.json()["activeVersionId"] is None
    assert app_module.store.verify_audit_chain(app_module.settings.tenant_id)


def test_stale_suggestion_cannot_overwrite_user_edits(client):
    from extrio.field_suggestions import claim_suggestion, finish_suggestion

    col = requirement(client)
    suggestion = enqueue(client, col)
    job = claim_suggestion(app_module.store)
    finish_suggestion(app_module.store, job, fields=FIELDS)
    command(client, "PATCH", f"/api/v1/collections/{col['id']}", {"revision": col["revision"], "intent": "User edited intent"}, "user-edit")
    response = command(
        client,
        "POST",
        f"/api/v1/collections/{col['id']}/field-suggestions/{suggestion['id']}/apply",
        {"revision": col["revision"] + 1, "selectedKeys": ["title"]},
        "stale-apply",
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/collections/{col['id']}").json().get("fieldDraft") is None


@pytest.mark.asyncio
async def test_suggestion_failure_is_recoverable_and_never_a_success(client):
    from extrio.field_suggestions import claim_suggestion

    col = requirement(client)
    suggestion = enqueue(client, col)
    job = claim_suggestion(app_module.store)
    worker = Worker.__new__(Worker)
    worker.store = app_module.store
    worker.fail(job, RuntimeError("private diagnostic must not be returned"))
    result = client.get(f"/api/v1/collections/{col['id']}/field-suggestions").json()["items"][0]
    assert result["id"] == suggestion["id"]
    assert result["status"] == "failed"
    assert result["fields"] == []
    assert "private diagnostic" not in str(result)
    assert enqueue(client, col, "retry-suggestion")["status"] == "queued"


def test_suggestion_reclaim_fences_old_attempt_and_limits_recovery(client):
    from extrio.field_suggestions import claim_suggestion, finish_suggestion

    col = requirement(client)
    suggestion = enqueue(client, col)
    old = claim_suggestion(app_module.store)
    assert claim_suggestion(app_module.store) is None
    with app_module.store.transaction() as conn:
        conn.execute("UPDATE field_suggestions SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", suggestion["id"]))
    replacement = claim_suggestion(app_module.store)
    assert replacement["payload"]["attempt"] == 2
    assert finish_suggestion(app_module.store, old, fields=FIELDS) is False
    with app_module.store.transaction() as conn:
        conn.execute("UPDATE field_suggestions SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", suggestion["id"]))
    assert claim_suggestion(app_module.store)["payload"]["attempt"] == 3
    with app_module.store.transaction() as conn:
        conn.execute("UPDATE field_suggestions SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", suggestion["id"]))
    assert claim_suggestion(app_module.store) is None
    result = client.get(f"/api/v1/collections/{col['id']}/field-suggestions").json()["items"][0]
    assert result["status"] == "failed"
    assert result["error"]["code"] == "SUGGESTION_ATTEMPTS_EXHAUSTED"


def test_suggestion_rate_limit_and_idempotency(client):
    from extrio.field_suggestions import claim_suggestion, finish_suggestion

    col = requirement(client)
    first = enqueue(client, col)
    assert enqueue(client, col)["id"] == first["id"]
    for index in range(5):
        if index:
            enqueue(client, col, f"start-{index}")
        finish_suggestion(app_module.store, claim_suggestion(app_module.store), fields=FIELDS)
    response = command(client, "POST", f"/api/v1/collections/{col['id']}/field-suggestions", {"revision": col["revision"]}, "sixth-start")
    assert response.status_code == 429


def test_invalid_model_fields_and_selection_never_modify_draft(client):
    from extrio.field_suggestions import claim_suggestion, finish_suggestion

    col = requirement(client)
    suggestion = enqueue(client, col)
    job = claim_suggestion(app_module.store)
    for fields in ([], [FIELDS[0], FIELDS[0]], [{**FIELDS[0], "key": "__proto__"}], [{**FIELDS[0], "type": "python"}]):
        with pytest.raises(ValueError):
            finish_suggestion(app_module.store, job, fields=fields)
    assert finish_suggestion(app_module.store, job, fields=FIELDS)
    for index, keys in enumerate(([], ["unknown"], ["title", "title"])):
        response = command(
            client,
            "POST",
            f"/api/v1/collections/{col['id']}/field-suggestions/{suggestion['id']}/apply",
            {"revision": 1, "selectedKeys": keys},
            f"invalid-selection-{index}",
        )
        assert response.status_code == 422
    assert client.get(f"/api/v1/collections/{col['id']}").json().get("fieldDraft") is None


def test_template_transaction_rolls_back_on_audit_failure(client, monkeypatch):
    col = requirement(client)
    from extrio.field_suggestions import field_workflow_command

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(app_module.store, "_append_audit_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        field_workflow_command(
            app_module.store,
            col["id"],
            "apply-template",
            {"revision": 1, "templateId": "public_notices_v1"},
            "rollback-test-key",
            {"tenantId": "tenant_demo"},
        )
    assert app_module.store.get_collection(col["id"])["revision"] == 1
    assert app_module.store.get_collection(col["id"]).get("fieldDraft") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_real_gateway_path_records_usage_and_cancelled_calls_truthfully(client, monkeypatch, tmp_path, cancelled):
    import asyncio
    import json

    import extrio.model_gateway as gateway
    from extrio.credentials import CredentialCipher
    from extrio.field_suggestions import claim_suggestion, list_suggestions

    col = requirement(client)
    enqueue(client, col)
    job = claim_suggestion(app_module.store)

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": json.dumps({"fields": FIELDS})}}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45},
            }

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 90

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            assert kwargs["json"]["max_tokens"] == 4096
            assert json.loads(kwargs["json"]["messages"][1]["content"])["intent"] == col["intent"]
            if cancelled:
                raise asyncio.CancelledError()
            return Response()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", Client)
    compiler = gateway.ModelRuleCompiler(app_module.store, CredentialCipher(tmp_path / "cipher.key"))
    monkeypatch.setattr(
        compiler,
        "_model",
        lambda: gateway.ActiveModel(
            provider="openai", base_url="https://example.com/v1", model="test-model", api_key="never-record-this-secret"
        ),
    )
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await compiler.suggest_fields(job["payload"]["snapshot"], job["id"], job["payload"]["attempt"])
    else:
        assert await compiler.suggest_fields(job["payload"]["snapshot"], job["id"], job["payload"]["attempt"]) == FIELDS
    record = list_suggestions(app_module.store, col["id"])[0]
    invocation = record["modelInvocations"][0]
    assert invocation["status"] == ("failed" if cancelled else "succeeded")
    assert invocation["totalTokens"] == (0 if cancelled else 168)
    assert "never-record-this-secret" not in str(record)
    assert "snapshot" not in record


# ruff: noqa: F811
# Pytest injects the imported fixtures by parameter name.
