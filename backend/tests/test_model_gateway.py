from pathlib import Path

import pytest

import extrio.model_gateway as model_gateway
from extrio.credentials import CredentialCipher
from extrio.model_gateway import ActiveModel, ModelRuleCompiler, _dom_evidence, _json_content, normalize_discovery_plan, normalize_rule_plan
from extrio.store import Store


def test_json_content_accepts_compact_and_fenced_responses() -> None:
    assert _json_content('{"approved":true}') == {"approved": True}
    assert _json_content('```json\n{"approved": false, "reason": "missing"}\n```')["reason"] == "missing"


@pytest.mark.asyncio
async def test_model_call_records_usage_and_response_digest_without_raw_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": '{"mode":"single"}'}}],
                "usage": {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366},
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(model_gateway.httpx, "AsyncClient", FakeClient)
    store = Store(tmp_path / "model-run.db")
    store.initialize()
    collector = store.create_collector("Demo", "Collect", "https://example.com/list", "example.com")
    store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"], "aiRunId": "ai_run_model"},
        ai_run={
            "id": "ai_run_model",
            "collectorId": collector["id"],
            "collectorName": collector["name"],
            "sourceUrl": collector["sourceUrl"],
            "kind": "rule_generation",
            "trigger": "initial_generation",
            "initiatedBy": "user_demo",
        },
    )
    attempt = store.start_ai_attempt("ai_run_model")
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / "key"))

    result = await compiler._complete_json(
        ActiveModel(provider="openai", base_url="https://models.example.com/v1", model="model-a", api_key="secret"),
        "system prompt",
        {"sourceUrl": "https://example.com/list", "domEvidence": "sensitive page content"},
        ai_run_id="ai_run_model",
        attempt_id=attempt["id"],
        purpose="discover",
        prompt_version="2.0",
    )

    assert result == {"mode": "single"}
    invocation = store.get_ai_run("ai_run_model")["attempts"][0]["modelInvocations"][0]
    assert invocation["totalTokens"] == 366
    assert invocation["responseDigest"].startswith("sha256:")
    assert "prompt" not in invocation
    assert "sensitive page content" not in str(invocation)


def test_dom_evidence_removes_active_content_but_keeps_structure_and_text() -> None:
    evidence = _dom_evidence(
        '<html><script>ignore()</script><style>.x{}</style><main id="records"><a class="title" href="/42">项目 A</a></main></html>'
    )

    assert "ignore" not in evidence
    assert "<style" not in evidence
    assert 'id="records"' in evidence
    assert 'class="title"' in evidence
    assert "项目 A" in evidence


def test_discovery_plan_is_normalized_to_the_deterministic_selector_dialect() -> None:
    plan = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "transport": "browser",
            "list": {
                "responseType": "html",
                "itemsSelector": ".records > article",
                "fields": {
                    "listTitle": {"selector": "h2::text", "required": True},
                    "detailUrl": {"selector": "a::attr(href)", "required": True},
                },
                "pagination": {"type": "next_link", "selector": "a.next", "maxPages": 25},
            },
        }
    )

    assert plan["list"]["itemsSelector"] == "css:.records > article"
    assert plan["list"]["fields"]["detailUrl"]["selector"] == "css:a::attr(href)"
    assert plan["list"]["fields"]["detailUrl"]["transforms"] == ["trim", "absolute_url"]
    assert plan["list"]["pagination"] == {
        "type": "next_link",
        "selector": "css:a.next",
        "maxPages": 25,
        "allowCrossHost": False,
    }


def test_html_field_rules_gain_deterministic_value_accessors() -> None:
    plan = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {
                    "title": {"selector": "a.title", "required": True},
                    "detailUrl": {"selector": "a.title", "valueType": "url", "required": True},
                },
                "pagination": {"type": "none"},
            },
        }
    )

    assert plan["list"]["fields"]["title"]["selector"] == "css:a.title::text"
    assert plan["list"]["fields"]["detailUrl"]["selector"] == "css:a.title::attr(href)"


def test_final_plan_keeps_proven_pagination_when_model_suggests_unsupported_pattern() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {"detailUrl": {"selector": "a::attr(href)", "required": True}},
                "pagination": {"type": "none"},
            },
        }
    )

    plan = normalize_rule_plan(
        {
            "list": {"pagination": {"type": "numbered_url_pattern", "template": "index_{page}.htm"}},
            "detail": {
                "responseType": "html",
                "fields": {"title": {"selector": "h1::text", "required": True}},
            },
            "identityFields": ["detailUrl"],
            "fingerprintFields": ["title"],
        },
        discovery,
    )

    assert plan["list"]["pagination"] == {"type": "none"}


def test_final_plan_keeps_proven_browser_transport() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "transport": "browser",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {"detailUrl": {"selector": "a::attr(href)", "required": True}},
                "pagination": {"type": "none"},
            },
        }
    )

    plan = normalize_rule_plan(
        {
            "transport": "http",
            "detail": {"responseType": "html", "fields": {"title": {"selector": "h1::text"}}},
            "identityFields": ["detailUrl"],
            "fingerprintFields": ["title"],
        },
        discovery,
    )

    assert plan["transport"] == "browser"
