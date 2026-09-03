import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import extrio.app as app_module
import extrio.explorer as explorer_module
import extrio.model_gateway as model_gateway
from extrio.contracts import sha256_digest
from extrio.credentials import CredentialCipher
from extrio.explorer import Crawl4AIExplorer, ExplorationResult
from extrio.harvest import build_candidate, build_gather_spec_from_plan
from extrio.model_gateway import (
    ActiveModel,
    ModelRepairNotApplicableError,
    ModelRepairValidationError,
    ModelRuleCompiler,
    normalize_discovery_plan,
    normalize_rule_plan,
)
from extrio.store import Store
from extrio.worker import Worker

ACTIVE_MODEL = ActiveModel(provider="openai", base_url="https://models.example.com/v1", model="model-a", api_key="test-key")

OLD_LIST_HTML = (
    '<ul class="old-list"><li><a class="old-title" href="/detail/1">项目A</a>'
    '<time class="old-date" datetime="2026-08-30"></time></li>'
    '<li><a class="old-title" href="/detail/2">项目B</a>'
    '<time class="old-date" datetime="2026-08-31"></time></li></ul>'
)
NEW_DETAIL_HTML = (
    '<article><h1 class="new-detail-title">项目A</h1>'
    '<time class="new-published" datetime="2026-08-30T00:00:00Z"></time>'
    '<div class="new-content"><p>公告正文</p></div></article>'
)
BROKEN_LIST_HTML = '<ul class="new-list"><li>站点已改版，暂无公告</li></ul>'

OLD_DISCOVERY_DRAFT = {
    "mode": "list_detail",
    "transport": "browser",
    "list": {
        "responseType": "html",
        "itemsSelector": "ul.old-list > li",
        "fields": {
            "listTitle": {"selector": "a.old-title", "label": "列表标题", "required": True},
            "listPublishedAt": {"selector": "time.old-date", "required": True},
            "detailUrl": {"selector": "a.old-title", "valueType": "url", "required": True},
        },
        "pagination": {"type": "next_link", "selector": "a.old-next", "maxPages": 5},
    },
}
OLD_FINAL_DRAFT = {
    "detail": {
        "responseType": "html",
        "fields": {
            "title": {"selector": "h1.old-detail-title", "label": "项目名称", "required": True},
            "publishedAt": {"selector": "time.old-published", "valueType": "datetime", "required": True},
            "content": {"selector": "div.old-content", "valueType": "html", "required": False},
        },
    },
    "identityFields": ["detailUrl"],
    "fingerprintFields": ["title", "publishedAt", "content"],
    "bindings": {
        "detailUrl": "list.detailUrl",
        "listTitle": "list.listTitle",
        "listPublishedAt": "list.listPublishedAt",
        "title": "detail.title",
        "publishedAt": "detail.publishedAt",
        "content": "detail.content",
    },
    "rationale": "初始编译规则",
}
FULLY_REPAIRED_RESPONSE = {
    "mode": "list_detail",
    "transport": "browser",
    "list": {
        "itemsSelector": "ul.new-list > li",
        "fields": {
            "listTitle": {"selector": "a.new-title::text"},
            "listPublishedAt": {"selector": "time.new-date::attr(datetime)"},
            "detailUrl": {"selector": "a.new-title::attr(href)"},
        },
        "pagination": {"type": "next_link", "selector": "a.new-next", "maxPages": 5},
    },
    "detail": {
        "fields": {
            "title": {"selector": "h1.new-detail-title::text"},
            "publishedAt": {"selector": "time.new-published::attr(datetime)"},
            "content": {"selector": "div.new-content::html"},
        }
    },
    "rationale": "站点改版，更新列表与详情 selector。",
}
DETAIL_ONLY_REPAIR_RESPONSE = {
    "mode": "list_detail",
    "transport": "browser",
    "list": {
        "itemsSelector": "css:ul.old-list > li",
        "fields": {
            "listTitle": {"selector": "css:a.old-title::text"},
            "listPublishedAt": {"selector": "css:time.old-date::attr(datetime)"},
            "detailUrl": {"selector": "css:a.old-title::attr(href)"},
        },
        "pagination": {"type": "none"},
    },
    "detail": {
        "fields": {
            "title": {"selector": "h1.new-detail-title::text"},
            "publishedAt": {"selector": "time.new-published::attr(datetime)"},
            "content": {"selector": "div.new-content::html"},
        }
    },
    "rationale": "详情页改版，更新详情 selector 并移除失效分页。",
}
E2E_LIST_HTML = (
    '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">Notice A</a>'
    '<time datetime="2026-08-30"></time></li></ul>'
)
E2E_DETAIL_HTML = (
    '<article class="notice-article"><h1 class="article-headline">Notice A</h1>'
    '<p class="article-agency">Buyer</p><time class="article-date" datetime="2026-08-30"></time>'
    '<div class="article-amount">100</div></article>'
)
E2E_REPAIR_RESPONSE = {
    "mode": "list_detail",
    "transport": "http",
    "list": {
        "itemsSelector": "css:.notice-list > li",
        "fields": {
            "listTitle": {"selector": "css:a.notice-title::text"},
            "listPublishedAt": {"selector": "css:time::attr(datetime)"},
            "detailUrl": {"selector": "css:a.notice-title::attr(href)"},
        },
        "pagination": {"type": "none"},
    },
    "detail": {
        "fields": {
            "title": {"selector": "css:h1.article-headline::text"},
            "buyer": {"selector": "css:p.article-agency::text"},
            "publishedAt": {"selector": "css:time.article-date::attr(datetime)"},
            "budget": {"selector": "css:.article-amount::text"},
        }
    },
    "rationale": "详情页改版，更新详情字段 selector。",
}


async def _noop_progress(_phase: str, _value: int, _metrics: dict) -> None:
    return None


def make_store(tmp_path: Path, name: str = "repair") -> Store:
    store = Store(tmp_path / f"{name}.db")
    store.initialize()
    return store


def install_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_gateway.ModelRuleCompiler, "_model", lambda _self: ACTIVE_MODEL)


def install_llm(monkeypatch: pytest.MonkeyPatch, content: str) -> list[dict]:
    captured: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, headers=None, json=None):
            captured.append(json)
            return FakeResponse()

    monkeypatch.setattr(model_gateway.httpx, "AsyncClient", FakeClient)
    return captured


def install_crawler(monkeypatch: pytest.MonkeyPatch, pages: dict[str, str]) -> None:
    class FakeResult:
        def __init__(self, html: str):
            self.success = True
            self.html = html

    class FakeCrawler:
        def __init__(self, page_map: dict[str, str]):
            self._pages = page_map

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def arun(self, url, config=None):
            return FakeResult(self._pages[url])

    instance = FakeCrawler(pages)
    monkeypatch.setattr(explorer_module, "AsyncWebCrawler", lambda **_kwargs: instance)


def old_rule_fixtures(store: Store) -> tuple[dict, dict]:
    collector = store.create_collector("Demo", "采集招标公告", "https://example.com/list", "example.com")
    discovery = normalize_discovery_plan(OLD_DISCOVERY_DRAFT)
    plan = normalize_rule_plan(OLD_FINAL_DRAFT, discovery)
    return collector, build_gather_spec_from_plan(collector, app_module.contracts, plan)


def repaired_response(**overrides) -> dict:
    response = copy.deepcopy(FULLY_REPAIRED_RESPONSE)
    response.update(overrides)
    return response


def collector_with_candidate(store: Store) -> dict:
    collector = store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
    detail_html = (
        '<h1 class="notice-title">Notice A</h1><div class="meta"><span data-field="buyer">Buyer</span>'
        '<time datetime="2026-08-30"></time></div><div class="notice-budget"><span class="amount">100</span></div>'
    )
    collector.update(
        status="ready_review",
        candidate=build_candidate(collector, app_module.contracts, E2E_LIST_HTML, [("https://example.com/detail/1", detail_html)]),
    )
    store.save_collector(collector)
    return collector


def create_repair_ai_run(store: Store, collector: dict, ai_run_id: str) -> None:
    store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"], "previousStatus": collector["status"], "aiRunId": ai_run_id, "repair": True},
        collector_changes={"status": "exploring"},
        ai_run={
            "id": ai_run_id,
            "collectorId": collector["id"],
            "collectorName": collector["name"],
            "sourceUrl": collector["sourceUrl"],
            "kind": "rule_repair",
            "trigger": "repair",
            "initiatedBy": "user_demo",
        },
    )


@pytest.mark.asyncio
async def test_repair_compilation_embeds_old_rule_and_reuses_normalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    collector, old_spec = old_rule_fixtures(store)
    install_model(monkeypatch)
    captured = install_llm(monkeypatch, json.dumps(repaired_response()))
    create_repair_ai_run(store, collector, "ai_run_repair")
    attempt = store.start_ai_attempt("ai_run_repair")
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / "cipher.key"))

    result = await compiler.compile_repair_rule_plan(
        collector,
        "https://example.com/list",
        BROKEN_LIST_HTML,
        [("https://example.com/detail/1", NEW_DETAIL_HTML)],
        old_spec,
        ai_run_id="ai_run_repair",
        attempt_id=attempt["id"],
    )

    evidence = json.loads(captured[0]["messages"][1]["content"])
    assert evidence["oldRule"]["list"]["itemsSelector"] == old_spec["collect"]["list"]["itemsSelector"]
    assert evidence["oldRule"]["list"]["fields"]["detailUrl"]["selector"] == "css:a.old-title::attr(href)"
    assert evidence["oldRule"]["detail"]["fields"]["title"]["selector"] == "css:h1.old-detail-title::text"
    assert evidence["oldRule"]["contract"]["identityFields"] == old_spec["contract"]["identityFields"]
    assert evidence["oldRule"]["contract"]["outputFieldNames"] == list(old_spec["contract"]["normalizedItemSchema"]["properties"])
    assert "repair" in captured[0]["messages"][0]["content"]

    plan = result.plan
    assert result.agent == {
        "provider": "openai",
        "model": "model-a",
        "promptVersion": "2.1-repair",
        "toolchainVersion": "2.0",
    }
    assert set(plan["list"]["fields"]) == set(old_spec["collect"]["list"]["fields"])
    assert set(plan["detail"]["fields"]) == set(old_spec["collect"]["detail"]["fields"])
    assert plan["list"]["itemsSelector"] == "css:ul.new-list > li"
    assert plan["list"]["fields"]["detailUrl"]["selector"] == "css:a.new-title::attr(href)"
    assert plan["detail"]["fields"]["title"]["selector"] == "css:h1.new-detail-title::text"
    assert plan["detail"]["fields"]["publishedAt"]["valueType"] == "datetime"
    old_published_at = old_spec["collect"]["detail"]["fields"]["publishedAt"]
    assert plan["detail"]["fields"]["publishedAt"]["datetimeFormat"] == old_published_at["datetimeFormat"]
    assert plan["list"]["fields"]["listTitle"]["label"] == "列表标题"
    assert plan["detail"]["fields"]["title"]["label"] == "项目名称"
    assert plan["identityFields"] == old_spec["contract"]["identityFields"]
    assert plan["bindings"] == old_spec["contract"]["fieldBindings"]
    assert plan["list"]["pagination"]["type"] == "next_link"
    assert plan["list"]["pagination"]["selector"] == "css:a.new-next"
    assert plan["list"]["pagination"]["maxPages"] == 5

    invocation = store.get_ai_run("ai_run_repair")["attempts"][0]["modelInvocations"][0]
    assert invocation["purpose"] == "repair"
    assert invocation["promptVersion"] == "2.1-repair"
    assert invocation["status"] == "succeeded"


@pytest.mark.asyncio
async def test_repair_compilation_fails_when_output_field_cannot_be_mapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    collector, old_spec = old_rule_fixtures(store)
    install_model(monkeypatch)
    response = repaired_response()
    del response["detail"]["fields"]["content"]
    install_llm(monkeypatch, json.dumps(response))
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / "cipher.key"))

    with pytest.raises(ModelRepairValidationError) as exc_info:
        await compiler.compile_repair_rule_plan(
            collector,
            "https://example.com/list",
            BROKEN_LIST_HTML,
            [("https://example.com/detail/1", NEW_DETAIL_HTML)],
            old_spec,
        )

    assert exc_info.value.code == "REPAIR_VALIDATION_FAILED"
    assert "content" in str(exc_info.value)
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_repair_compilation_rejects_unexpected_output_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    collector, old_spec = old_rule_fixtures(store)
    install_model(monkeypatch)
    response = repaired_response()
    response["detail"]["fields"]["summary"] = {"selector": "p.new-summary::text"}
    install_llm(monkeypatch, json.dumps(response))
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / "cipher.key"))

    with pytest.raises(ModelRepairValidationError) as exc_info:
        await compiler.compile_repair_rule_plan(
            collector,
            "https://example.com/list",
            BROKEN_LIST_HTML,
            [("https://example.com/detail/1", NEW_DETAIL_HTML)],
            old_spec,
        )

    assert exc_info.value.code == "REPAIR_VALIDATION_FAILED"
    assert "summary" in str(exc_info.value)


@pytest.mark.asyncio
async def test_repair_compilation_falls_back_to_old_pagination_when_model_suggests_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    collector, old_spec = old_rule_fixtures(store)
    install_model(monkeypatch)
    response = repaired_response()
    response["list"]["pagination"] = {"type": "numbered_url_pattern", "template": "index_{page}.htm"}
    install_llm(monkeypatch, json.dumps(response))
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / "cipher.key"))

    result = await compiler.compile_repair_rule_plan(
        collector,
        "https://example.com/list",
        BROKEN_LIST_HTML,
        [("https://example.com/detail/1", NEW_DETAIL_HTML)],
        old_spec,
    )

    assert result.plan["list"]["pagination"] == old_spec["collect"]["list"]["pagination"]


def test_apply_repair_contract_forces_old_contract_and_logs_drift(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _store, old_spec = old_rule_fixtures(make_store(tmp_path))
    drifted_spec = copy.deepcopy(old_spec)
    drifted_spec["contract"]["identityFields"] = ["title"]
    drifted_spec["contract"]["normalizedItemSchema"]["properties"].pop("content")
    drifted_spec["contract"]["fieldBindings"] = {}
    candidate = {"gatherSpec": drifted_spec}

    with caplog.at_level("WARNING", logger="extrio.explorer"):
        explorer_module._apply_repair_contract(candidate, old_spec)

    assert candidate["gatherSpec"]["contract"] == old_spec["contract"]
    assert candidate["gatherSpec"]["contract"]["outputContractDigest"] == old_spec["contract"]["outputContractDigest"]
    assert any("forced the previous contract" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_repair_explore_updates_detail_selectors_and_preserves_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, "explore-repair")
    collector, old_spec = old_rule_fixtures(store)
    install_model(monkeypatch)
    install_llm(monkeypatch, json.dumps(DETAIL_ONLY_REPAIR_RESPONSE))
    install_crawler(
        monkeypatch,
        {
            "https://example.com/list": OLD_LIST_HTML,
            "https://example.com/detail/1": NEW_DETAIL_HTML,
            "https://example.com/detail/2": NEW_DETAIL_HTML,
        },
    )
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / "cipher.key"))
    explorer = Crawl4AIExplorer(app_module.contracts, tmp_path / "artifacts", compiler)

    result = await explorer.explore(collector, "op_repair_1", _noop_progress, repair_spec=old_spec)

    spec = result.candidate["gatherSpec"]
    assert spec["contract"] == old_spec["contract"]
    assert spec["collect"]["list"]["itemsSelector"] == "css:ul.old-list > li"
    assert spec["collect"]["list"]["fields"]["detailUrl"]["selector"] == "css:a.old-title::attr(href)"
    assert spec["collect"]["detail"]["fields"]["title"]["selector"] == "css:h1.new-detail-title::text"
    assert spec["collect"]["detail"]["fields"]["publishedAt"]["valueType"] == "datetime"
    assert spec["collect"]["detail"]["fields"]["content"]["valueType"] == "html"
    assert spec["collect"]["list"]["pagination"] == {"type": "none"}
    assert spec["compiler"]["agent"]["promptVersion"] == "2.1-repair"
    assert result.candidate["digest"] == sha256_digest(spec)
    assert sum(item["decision"] == "accepted" for item in result.preview_items) == 2


@pytest.mark.asyncio
async def test_repair_explore_fails_when_identity_field_cannot_be_extracted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path, "explore-repair-fail")
    collector, old_spec = old_rule_fixtures(store)
    install_model(monkeypatch)
    install_llm(monkeypatch, json.dumps(DETAIL_ONLY_REPAIR_RESPONSE))
    broken_list_html = '<ul class="old-list"><li>站点已改版，暂无公告</li></ul>'
    install_crawler(monkeypatch, {"https://example.com/list": broken_list_html})
    compiler = ModelRuleCompiler(store, CredentialCipher(tmp_path / "cipher.key"))
    explorer = Crawl4AIExplorer(app_module.contracts, tmp_path / "artifacts", compiler)

    with pytest.raises(ModelRepairValidationError) as exc_info:
        await explorer.explore(collector, "op_repair_2", _noop_progress, repair_spec=old_spec)

    assert exc_info.value.code == "REPAIR_VALIDATION_FAILED"
    assert "detailUrl" in str(exc_info.value)


@pytest.mark.asyncio
async def test_worker_repair_job_reads_old_spec_and_returns_collector_to_review(tmp_path: Path) -> None:
    store = make_store(tmp_path, "worker-repair")
    collector = collector_with_candidate(store)
    old_gather_spec = copy.deepcopy(collector["candidate"]["gatherSpec"])
    captured: dict = {}

    class FakeExplorer:
        async def explore(self, explored_collector, _operation_id, progress, _ai_run_id=None, _attempt_id=None, *, repair_spec=None):
            captured["repair_spec"] = copy.deepcopy(repair_spec)
            await progress("fetching_list", 20, {"listPagesFetched": 1, "warningCount": 0})
            repaired = build_candidate(
                explored_collector,
                app_module.contracts,
                '<ul class="notice-list"><li><a class="notice-title" href="/detail/2">Notice B</a>'
                '<time datetime="2026-09-01"></time></li></ul>',
                [("https://example.com/detail/2", '<h1 class="notice-title">Notice B</h1>')],
            )
            return ExplorationResult(candidate=repaired, preview_items=[{"decision": "accepted"}], metrics={"warningCount": 0})

    create_repair_ai_run(store, collector, "ai_run_repair_worker")
    job = store.claim_job(60)
    assert job is not None
    assert job["payload"]["repair"] is True
    worker = Worker.__new__(Worker)
    worker.store = store
    worker.explorer = FakeExplorer()

    await worker.process(job)

    assert captured["repair_spec"] == old_gather_spec
    updated = store.get_collector(collector["id"])
    assert updated["status"] == "ready_review"
    assert updated["reviewDecisions"] is None
    assert updated["candidate"]["digest"] != collector["candidate"]["digest"]
    ai_run = store.get_ai_run("ai_run_repair_worker")
    assert ai_run["status"] == "succeeded"
    assert ai_run["kind"] == "rule_repair"
    assert ai_run["reviewStatus"] == "ready_review"


@pytest.mark.asyncio
async def test_worker_repair_without_rule_fails_with_repair_not_applicable(tmp_path: Path) -> None:
    store = make_store(tmp_path, "worker-repair-invalid")
    collector = store.create_collector("Empty", "Collect", "https://example.com/list", "example.com")
    create_repair_ai_run(store, collector, "ai_run_repair_invalid")
    job = store.claim_job(60)
    assert job is not None
    worker = Worker.__new__(Worker)
    worker.store = store

    with pytest.raises(ModelRepairNotApplicableError) as exc_info:
        await worker.process(job)
    worker.fail(job, exc_info.value)

    operation = store.get_operation(job["operationId"])
    assert operation["status"] == "failed"
    assert operation["error"]["code"] == "REPAIR_NOT_APPLICABLE"
    ai_run = store.get_ai_run("ai_run_repair_invalid")
    assert ai_run["status"] == "failed"
    assert ai_run["error"]["code"] == "REPAIR_NOT_APPLICABLE"
    restored = store.get_collector(collector["id"])
    assert restored["status"] == "draft"
    assert restored["activeOperationId"] is None


def test_repairs_endpoint_creates_rule_repair_operation_and_replays(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path, "api-repair")
    try:
        with TestClient(app_module.app) as client:
            collector = collector_with_candidate(app_module.store)
            accepted = client.post(
                f"/api/v1/collectors/{collector['id']}/repairs",
                headers={"Idempotency-Key": "repair-command-0001"},
                json={"note": "站点改版导致规则失效"},
            )
            assert accepted.status_code == 202, accepted.json()
            operation = accepted.json()
            assert operation["kind"] == "explore"
            assert accepted.headers["Location"] == operation["statusUrl"]
            assert client.get(f"/api/v1/collectors/{collector['id']}").json()["status"] == "exploring"

            replay = client.post(
                f"/api/v1/collectors/{collector['id']}/repairs",
                headers={"Idempotency-Key": "repair-command-0001"},
                json={"note": "站点改版导致规则失效"},
            )
            assert replay.status_code == 202
            assert replay.headers["Idempotency-Replayed"] == "true"

            runs = client.get("/api/v1/ai-runs").json()["items"]
            assert runs[0]["kind"] == "rule_repair"
            assert runs[0]["trigger"] == "repair"
            assert runs[0]["note"] == "站点改版导致规则失效"

            job = app_module.store.claim_job(60)
            assert job is not None
            assert job["payload"]["repair"] is True
            assert job["payload"]["previousStatus"] == "ready_review"
    finally:
        app_module.store = original


def test_repairs_endpoint_rejects_collector_without_rule(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path, "api-repair-invalid")
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Empty", "Collect", "https://example.com/list", "example.com")
            response = client.post(
                f"/api/v1/collectors/{collector['id']}/repairs",
                headers={"Idempotency-Key": "repair-invalid-0001"},
            )
            assert response.status_code == 409
            assert response.json()["code"] == "REPAIR_NOT_APPLICABLE"

            missing = client.post(
                "/api/v1/collectors/collector_missing/repairs",
                headers={"Idempotency-Key": "repair-missing-0001"},
            )
            assert missing.status_code == 404
            assert missing.json()["code"] == "COLLECTOR_NOT_FOUND"
    finally:
        app_module.store = original


def test_repairs_endpoint_conflicts_with_active_operation(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path, "api-repair-conflict")
    try:
        with TestClient(app_module.app) as client:
            collector = collector_with_candidate(app_module.store)
            exploration = client.post(
                f"/api/v1/collectors/{collector['id']}/explorations",
                headers={"Idempotency-Key": "explore-conflict-0001"},
            )
            assert exploration.status_code == 202
            repair = client.post(
                f"/api/v1/collectors/{collector['id']}/repairs",
                headers={"Idempotency-Key": "repair-conflict-0001"},
            )
            assert repair.status_code == 409
            assert repair.json()["code"] == "OPERATION_ALREADY_ACTIVE"
    finally:
        app_module.store = original


@pytest.mark.asyncio
async def test_repair_end_to_end_preserves_published_contract_and_returns_to_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path, "e2e-repair")
    install_model(monkeypatch)
    install_llm(monkeypatch, json.dumps(E2E_REPAIR_RESPONSE))
    install_crawler(
        monkeypatch,
        {
            "https://example.com/list": E2E_LIST_HTML,
            "https://example.com/detail/1": E2E_DETAIL_HTML,
        },
    )
    try:
        with TestClient(app_module.app) as client:
            collector = collector_with_candidate(app_module.store)
            old_contract = copy.deepcopy(collector["candidate"]["gatherSpec"]["contract"])
            published = client.post(
                f"/api/v1/collectors/{collector['id']}/publish",
                headers={"Idempotency-Key": "publish-repair-e2e-0001"},
                json={"reviewDecisions": {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}},
            )
            assert published.status_code == 200, published.json()
            rule_version = app_module.store.get_rule_version(published.json()["activeRuleVersion"])
            published_contract = copy.deepcopy(rule_version["gatherSpec"]["contract"])

            repair = client.post(
                f"/api/v1/collectors/{collector['id']}/repairs",
                headers={"Idempotency-Key": "repair-e2e-00001"},
                json={"note": "详情页改版"},
            )
            assert repair.status_code == 202, repair.json()
            job = app_module.store.claim_job(60)
            assert job is not None
            worker = Worker.__new__(Worker)
            worker.store = app_module.store
            worker.explorer = Crawl4AIExplorer(
                app_module.contracts,
                tmp_path / "artifacts",
                ModelRuleCompiler(app_module.store, CredentialCipher(tmp_path / "cipher.key")),
            )

            await worker.process(job)
            app_module.store.finish_job(job["id"])

            updated = app_module.store.get_collector(collector["id"])
            assert updated["status"] == "ready_review"
            spec = updated["candidate"]["gatherSpec"]
            assert spec["contract"] == old_contract
            assert spec["contract"] == published_contract
            assert spec["collect"]["detail"]["fields"]["title"]["selector"] == "css:h1.article-headline::text"
            assert spec["collect"]["detail"]["fields"]["publishedAt"]["valueType"] == "datetime"
            assert updated["candidate"]["digest"] == sha256_digest(spec)
            assert updated["activeOperationId"] is None
            assert any(
                field["key"] == "title" and field["selector"] == "css:h1.article-headline::text"
                for field in updated["candidate"]["fields"]
            )

            ai_run_id = client.get("/api/v1/ai-runs").json()["items"][0]["id"]
            ai_run = client.get(f"/api/v1/ai-runs/{ai_run_id}").json()
            assert ai_run["status"] == "succeeded"
            assert ai_run["kind"] == "rule_repair"
            assert ai_run["resultStatus"] == "candidate_ready"
            assert ai_run["candidateRuleDigest"] == updated["candidate"]["digest"]
            assert ai_run["attempts"][0]["modelInvocations"][0]["purpose"] == "repair"
            assert ai_run["attempts"][0]["modelInvocations"][0]["promptVersion"] == "2.1-repair"

            operation = client.get(repair.json()["statusUrl"]).json()
            assert operation["status"] == "succeeded"
    finally:
        app_module.store = original
