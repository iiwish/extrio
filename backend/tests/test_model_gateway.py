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


def test_detail_evidence_prioritizes_body_over_repeated_navigation() -> None:
    navigation = "".join(f'<li><a href="/{i}">Navigation item {i}</a></li>' for i in range(400))
    html = (
        f'<body><div class="menu"><ul>{navigation}</ul></div><div id="record"><h1>Project title</h1>'
        f'<div class="prose"><p>{"Actual project description. " * 40}</p></div></div></body>'
    )
    evidence = _dom_evidence(html, limit=14_000, stage="detail")
    assert len(evidence) <= 14_000
    assert 'id="record"' in evidence
    assert 'class="prose"' in evidence
    assert "Actual project description." in evidence
    assert "<repeated-record-groups>" not in evidence


def test_detail_evidence_bounds_long_text_without_losing_later_fields() -> None:
    html = f'<article id="notice"><p>{"Long text " * 5000}</p><table><tr><td class="budget">12345</td></tr></table></article>'
    evidence = _dom_evidence(html, limit=4000, stage="detail")
    assert len(evidence) <= 4000
    assert 'class="budget"' in evidence
    assert "12345" in evidence
    assert 'id="notice"' in evidence


def test_detail_evidence_preserves_head_metadata_for_exact_titles() -> None:
    html = '<html><head><meta name="ArticleTitle" content="Exact title"><title>Exact title - Portal</title></head>'
    html += '<body><div class="title">Exact title<p>Transaction 123</p></div><article>Body text</article></body></html>'
    evidence = _dom_evidence(html, limit=4000, stage="detail")
    assert '<meta content="Exact title" name="ArticleTitle"/>' in evidence
    assert "Transaction 123" in evidence
    assert len(evidence) <= 4000


@pytest.mark.asyncio
@pytest.mark.parametrize("repair", [False, True])
async def test_compile_and_repair_use_detail_specific_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repair: bool) -> None:
    compiler = ModelRuleCompiler(Store(tmp_path / "evidence.db"), CredentialCipher(tmp_path / "key"))
    monkeypatch.setattr(compiler, "_model", lambda: None)
    captured = {}

    class EvidenceCaptured(Exception):
        pass

    async def capture(_model, _system, evidence, **_kwargs):
        captured.update(evidence)
        raise EvidenceCaptured

    monkeypatch.setattr(compiler, "_complete_json", capture)
    old_spec = {"collect": {"list": {"fields": {"detailUrl": {}}}, "detail": {"fields": {"content": {}}}},
                "contract": {"identityFields": ["detailUrl"]}}
    with pytest.raises(EvidenceCaptured):
        method = compiler.compile_repair_rule_plan if repair else compiler.compile
        discovery = normalize_discovery_plan({'mode': 'list_detail', 'list': {
            'itemsSelector': 'li', 'fields': {'detailUrl': {'selector': 'css:a::attr(href)', 'valueType': 'url'}}}})
        await method({}, "https://example.com", "<a href='/1'>List</a>",
                     [("https://example.com/1", "<article>Detail body</article>")], old_spec if repair else discovery)
    assert "<detail-content-sample>" in captured["detailSamples"][0]["domEvidence"]
    assert "<repeated-record-groups>" in captured["listDomEvidence"]


@pytest.mark.asyncio
async def test_discovery_passes_bounded_operator_guidance_as_untrusted_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = ModelRuleCompiler(Store(tmp_path / "guidance.db"), CredentialCipher(tmp_path / "key"))
    captured: dict = {}
    monkeypatch.setattr(
        compiler,
        "_model",
        lambda: ActiveModel(provider="openai", base_url="https://models.example.com/v1", model="model-a", api_key="secret"),
    )

    async def fake_complete(_model, system, evidence, **_kwargs):
        captured["system"] = system
        captured["evidence"] = evidence
        return {
            "mode": "list_detail",
            "transport": "http",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {"detailUrl": {"selector": "a::attr(href)", "valueType": "url", "required": True}},
                "pagination": {"type": "none"},
            },
        }

    monkeypatch.setattr(compiler, "_complete_json", fake_complete)
    await compiler.discover(
        {"intent": "采集公告"},
        "https://example.com/list",
        '<li class="notice"><a href="/1">公告</a></li>',
        guidance="优先识别每行的详情入口。",
    )

    assert captured["evidence"]["operatorGuidance"] == "优先识别每行的详情入口。"
    assert "untrusted intent" in captured["system"]


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


def test_normalize_rule_plan_resolves_stage_prefixed_identity_and_fingerprint_fields() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "transport": "http",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {
                    "title": {"selector": "a::text", "required": True},
                    "detailUrl": {"selector": "a::attr(href)", "required": True},
                    "publishDate": {"selector": "span.date::text"},
                },
                "pagination": {"type": "none"},
            },
        }
    )

    plan = normalize_rule_plan(
        {
            "detail": {
                "responseType": "html",
                "fields": {
                    "heading": {"selector": "h1::text", "required": True},
                    "content": {"selector": "div.content::html"},
                },
            },
            "identityFields": ["list.detailUrl"],
            "fingerprintFields": ["list.title", "detail.heading"],
        },
        discovery,
    )

    assert plan["identityFields"] == ["detailUrl"]
    assert "heading" in plan["fingerprintFields"]
    assert "title" in plan["fingerprintFields"]
    assert "content" in plan["fingerprintFields"]


def test_normalize_rule_plan_falls_back_to_default_identity_when_unmatched() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "transport": "http",
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
            "detail": {
                "responseType": "html",
                "fields": {"heading": {"selector": "h1::text", "required": True}},
            },
            "identityFields": ["unknownField"],
            "fingerprintFields": ["unknownFingerprint"],
        },
        discovery,
    )

    assert plan["identityFields"] == ["detailUrl"]
    assert plan["fingerprintFields"] == ["heading"]


def test_normalize_rule_plan_aliases_common_field_variants() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "list_detail",
            "transport": "http",
            "list": {
                "responseType": "html",
                "itemsSelector": "li.notice",
                "fields": {
                    "detailUrl": {"selector": "a::attr(href)", "required": True},
                    "title": {"selector": "a::text", "required": True},
                    "publishDate": {"selector": "span.date::text", "required": False},
                },
                "pagination": {"type": "none"},
            },
        }
    )

    plan = normalize_rule_plan(
        {
            "detail": {
                "responseType": "html",
                "fields": {
                    "detailTitle": {"selector": "h1.title::text", "required": True},
                    "detailPublishDate": {"selector": "span.time::text", "required": False},
                    "detailContent": {"selector": "div.content::html", "required": True},
                },
            },
            "identityFields": ["detailTitle"],
            "fingerprintFields": ["detailTitle", "detailPublishDate", "detailContent"],
        },
        discovery,
    )

    assert "title" in plan["detail"]["fields"]
    assert "publishDate" in plan["detail"]["fields"]
    assert "content" in plan["detail"]["fields"]
    assert "detailTitle" not in plan["detail"]["fields"]
    assert plan["identityFields"] == ["title"]
    assert "title" in plan["fingerprintFields"]
    assert "publishDate" in plan["fingerprintFields"]
    assert "content" in plan["fingerprintFields"]
    assert plan["bindings"]["title"] == "detail.title"
    assert plan["bindings"]["publishedAt"] == "detail.publishDate"
    assert plan["bindings"]["content"] == "detail.content"


def test_normalize_rule_plan_maps_to_expected_fields_from_requirement() -> None:
    discovery = normalize_discovery_plan(
        {
            "mode": "single",
            "transport": "http",
            "list": {
                "responseType": "html",
                "itemsSelector": "div.row",
                "fields": {
                    "projName": {"selector": "h2::text", "required": True},
                    "org": {"selector": "span.buyer::text", "required": False},
                },
                "pagination": {"type": "none"},
            },
        }
    )

    expected_fields = [
        {"key": "title", "label": "项目名称", "type": "string", "required": True},
        {"key": "purchaser", "label": "采购单位", "type": "string", "required": False},
    ]

    plan = normalize_rule_plan(
        {
            "list": {
                "responseType": "html",
                "itemsSelector": "div.row",
                "fields": {
                    "projName": {"selector": "h2::text", "required": True},
                    "采购单位": {"selector": "span.buyer::text", "required": False},
                },
                "pagination": {"type": "none"},
            },
            "identityFields": ["projName"],
            "fingerprintFields": ["projName", "采购单位"],
        },
        discovery,
        expected_fields=expected_fields,
    )

    assert "title" in plan["list"]["fields"]
    assert "purchaser" in plan["list"]["fields"]
    assert plan["identityFields"] == ["title"]
    assert "title" in plan["fingerprintFields"]
    assert "purchaser" in plan["fingerprintFields"]
