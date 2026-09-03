"""Tests for the Extrio MCP server (no live LLM or browser required).

The tool functions are exercised through the in-memory MCP client session
(``create_connected_server_and_client_session``) against a temporary store,
plus a direct ASGI test for the bearer-token middleware. The tests follow the
repository convention of swapping ``extrio.app.store`` for a temporary store.
"""

from pathlib import Path
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import extrio.mcp_server as mcp_server
from extrio import app as control_plane
from extrio.harvest import build_candidate
from extrio.mcp_server import BearerTokenMiddleware
from extrio.store import Store

REVIEW_DECISIONS = {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}

# asyncio_mode=auto covers these, but the explicit marker also survives a
# strict-mode config flap (observed when the shared suite config changes).
pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(tmp_path: Path):
    original = control_plane.store
    store = Store(tmp_path / "mcp.db")
    store.initialize()
    control_plane.store = store
    try:
        yield store
    finally:
        control_plane.store = original


def seed_item(run_id: str, collector_id: str, *, observed_at: str, entity_key: str, decision: str = "accepted") -> dict[str, Any]:
    accepted = decision == "accepted"
    return {
        "id": f"item_{run_id}_{entity_key}",
        "collectorId": collector_id,
        "collectorName": "Tender Source",
        "sourceHost": "example.com",
        "listTitle": "Notice",
        "title": "Notice",
        "buyer": "Buyer",
        "region": "北京",
        "publishedAt": "2026-08-30",
        "budget": "100",
        "content": "Body",
        "sourceUrl": f"https://example.com/detail/{entity_key}",
        "decision": decision,
        "changeType": "new" if accepted else None,
        "rejectionReason": None if accepted else "必填字段 title 未通过非空质量门",
        "entityKey": entity_key,
        "revision": 1 if accepted else None,
        "observedAt": observed_at,
        "changeSummary": [],
        "observationHistory": (
            [{"id": f"obs_{entity_key}", "runId": run_id, "observedAt": observed_at, "outcome": "accepted"}] if accepted else []
        ),
        "lineage": {
            "sourceRevision": "source_revision_1",
            "collectionVersion": "tender_notice_v4",
            "ruleVersion": "rule_v1",
            "runId": run_id,
            "observationId": f"obs_{entity_key}" if accepted else None,
            "artifactId": f"artifact_{run_id}_{entity_key}",
        },
        "extractedData": {"title": "Notice", "buyer": "Buyer"},
    }


def seed_published_collector(store: Store) -> dict[str, Any]:
    """Create a collector and publish its rule through the real API path."""

    collector = store.create_collector("Tender Source", "Collect tender notices", "https://example.com/list", "example.com")
    list_html = '<ul class="notice-list"><li><a class="notice-title" href="/detail/1">A</a></li></ul>'
    detail_html = (
        '<h1 class="notice-title">A</h1><div class="meta"><span data-field="buyer">B</span>'
        '<time datetime="2026-08-31T00:00:00Z"></time></div>'
    )
    collector.update(
        status="ready_review",
        candidate=build_candidate(collector, control_plane.contracts, list_html, [("https://example.com/detail/1", detail_html)]),
    )
    store.save_collector(collector)
    published = control_plane.persist_published_rule(
        collector,
        rule_version_id=control_plane.next_rule_version_id(collector["id"], 1),
        review_decisions=REVIEW_DECISIONS,
        request_id="req_mcp_test",
        actor_id="tester",
    )
    return published


def seed_run_with_items(store: Store, collector: dict[str, Any]) -> str:
    run_id = "run_seed_0001"
    items = [
        seed_item(run_id, collector["id"], observed_at="2026-08-31 09:00", entity_key="entity_b"),
        seed_item(run_id, collector["id"], observed_at="2026-08-31 08:00", entity_key="entity_a"),
        seed_item(run_id, collector["id"], observed_at="2026-08-31 07:00", entity_key="entity_r", decision="rejected"),
    ]
    store.save_run(
        {
            "id": run_id,
            "collectorId": collector["id"],
            "collectorName": collector["name"],
            "status": "succeeded",
            "acceptedCount": 2,
            "rejectedCount": 1,
            "paginationStopReason": "no_next_page",
            "integrityStatus": "verified",
            "ruleVersion": collector.get("activeRuleVersion") or "candidate",
            "items": items,
        }
    )
    store.save_items(run_id, items)
    collector.update(latestRunId=run_id)
    store.save_collector(collector)
    return run_id


async def call_tool(session, name: str, arguments: dict[str, Any] | None = None):
    return await session.call_tool(name, arguments or {})


def result_payload(result) -> dict[str, Any]:
    assert not result.isError, result.content
    return result.structuredContent


def error_text(result) -> str:
    assert result.isError, result.content
    return str(result.content[0].text)


async def test_tool_catalog_lists_seven_governed_tools(store: Store) -> None:
    async with create_connected_server_and_client_session(mcp_server.build_server()) as session:
        tools = await session.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "list_collectors",
            "get_collector",
            "query_items",
            "get_item",
            "trigger_run",
            "create_collection",
            "get_run",
        }
        by_name = {tool.name: tool for tool in tools.tools}
        assert "human review" in by_name["create_collection"].description
        assert "no LLM" in by_name["trigger_run"].description


async def test_list_collectors_summaries(store: Store) -> None:
    collector = store.create_collector("Tender Source", "Collect tender notices", "https://example.com/list", "example.com")
    seed_run_with_items(store, collector)

    async with create_connected_server_and_client_session(mcp_server.build_server()) as session:
        result = await call_tool(session, "list_collectors")
    payload = result_payload(result)
    assert payload["count"] == 1
    summary = payload["collectors"][0]
    assert summary["id"] == collector["id"]
    assert summary["name"] == "Tender Source"
    assert summary["status"] == collector["status"]
    assert summary["sourceHost"] == "example.com"
    assert summary["scheduleEnabled"] is False
    assert summary["lastRun"]["id"] == "run_seed_0001"
    assert summary["lastRun"]["status"] == "succeeded"
    assert summary["lastRun"]["acceptedCount"] == 2
    assert summary["lastRun"]["startedAt"] is not None


async def test_query_items_pagination_and_filters(store: Store) -> None:
    collector = store.create_collector("Tender Source", "Collect tender notices", "https://example.com/list", "example.com")
    seed_run_with_items(store, collector)

    async with create_connected_server_and_client_session(mcp_server.build_server()) as session:
        page_one = result_payload(await call_tool(session, "query_items", {"collector_id": collector["id"], "limit": 2}))
        assert [item["entityKey"] for item in page_one["items"]] == ["entity_b", "entity_a"]
        assert page_one["items"][0]["extractedData"] == {"title": "Notice", "buyer": "Buyer"}
        assert page_one["nextCursor"] is not None

        page_two = result_payload(
            await call_tool(session, "query_items", {"collector_id": collector["id"], "limit": 2, "cursor": page_one["nextCursor"]})
        )
        assert [item["entityKey"] for item in page_two["items"]] == ["entity_r"]
        assert page_two["nextCursor"] is None

        rejected = result_payload(
            await call_tool(session, "query_items", {"collector_id": collector["id"], "decision": "rejected", "limit": 20})
        )
        assert [item["entityKey"] for item in rejected["items"]] == ["entity_r"]
        assert rejected["count"] == 1

        bad_decision = await call_tool(session, "query_items", {"decision": "approved"})
        assert "VALIDATION_FAILED" in error_text(bad_decision)

        bad_limit = await call_tool(session, "query_items", {"limit": 500})
        assert "VALIDATION_FAILED" in error_text(bad_limit)

        bad_cursor = await call_tool(session, "query_items", {"cursor": "not-a-cursor"})
        assert "INVALID_CURSOR" in error_text(bad_cursor)

        unknown_collector = await call_tool(session, "query_items", {"collector_id": "collector_missing"})
        assert "COLLECTOR_NOT_FOUND" in error_text(unknown_collector)


async def test_get_item_returns_full_record_and_errors_for_unknown(store: Store) -> None:
    collector = store.create_collector("Tender Source", "Collect tender notices", "https://example.com/list", "example.com")
    seed_run_with_items(store, collector)

    async with create_connected_server_and_client_session(mcp_server.build_server()) as session:
        item = result_payload(await call_tool(session, "get_item", {"item_id": "item_run_seed_0001_entity_b"}))
        assert item["id"] == "item_run_seed_0001_entity_b"
        assert item["extractedData"] == {"title": "Notice", "buyer": "Buyer"}
        assert item["lineage"]["runId"] == "run_seed_0001"
        assert item["observationHistory"][0]["outcome"] == "accepted"

        missing = await call_tool(session, "get_item", {"item_id": "item_missing"})
        assert "ITEM_NOT_FOUND" in error_text(missing)


async def test_create_collection_enqueues_governed_exploration(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    # v0.6 allows anonymous HTTP sources by default; pin the deny profile so the
    # HTTPS_REQUIRED rejection path of MCP creation stays covered.
    monkeypatch.setattr(control_plane.settings, "allow_http_public", False)
    async with create_connected_server_and_client_session(mcp_server.build_server()) as session:
        created = result_payload(
            await call_tool(
                session,
                "create_collection",
                {"name": "Gov Source", "intent": "Collect public tender notices", "entry_url": "https://example.gov.cn/list"},
            )
        )
        assert created["status"] == "exploring"
        assert created["operationId"]
        assert created["aiRunId"]
        assert "human review" in created["message"]
        assert "before any data is collected" in created["message"]

        duplicate = await call_tool(
            session,
            "create_collection",
            {"name": "Gov Source 2", "intent": "Collect", "entry_url": "https://example.gov.cn/list"},
        )
        assert "SOURCE_ALREADY_EXISTS" in error_text(duplicate)

        bad_scheme = await call_tool(
            session, "create_collection", {"name": "Gov", "intent": "Collect", "entry_url": "ftp://example.gov.cn/list"}
        )
        assert "INVALID_URL" in error_text(bad_scheme)

        plain_http = await call_tool(
            session, "create_collection", {"name": "Gov", "intent": "Collect", "entry_url": "http://example.gov.cn/list"}
        )
        assert "HTTPS_REQUIRED" in error_text(plain_http)

    collector = store.get_collector(created["collectorId"])
    assert collector["status"] == "exploring"
    assert collector["activeOperationId"] == created["operationId"]
    assert collector["sourceHost"] == "example.gov.cn"
    ai_runs = store.list_ai_runs(collector["id"])
    assert len(ai_runs) == 1
    assert ai_runs[0]["status"] == "queued"
    assert ai_runs[0]["reviewStatus"] == "not_ready"
    assert ai_runs[0]["initiatedBy"] == "mcp_agent"
    job = store.claim_job(60)
    assert job and job["kind"] == "explore" and job["payload"]["aiRunId"] == created["aiRunId"]


async def test_trigger_run_uses_published_rule_path_and_respects_active_run(store: Store) -> None:
    draft = store.create_collector("Draft Source", "Collect", "https://draft.example.com/list", "draft.example.com")
    async with create_connected_server_and_client_session(mcp_server.build_server()) as session:
        not_published = await call_tool(session, "trigger_run", {"collector_id": draft["id"]})
        assert "RULE_NOT_PUBLISHED" in error_text(not_published)

        unknown = await call_tool(session, "trigger_run", {"collector_id": "collector_missing"})
        assert "COLLECTOR_NOT_FOUND" in error_text(unknown)

        collector = seed_published_collector(store)
        started = result_payload(await call_tool(session, "trigger_run", {"collector_id": collector["id"]}))
        assert started["runId"] and started["operationId"]
        assert "deterministic" in started["message"]

        active = await call_tool(session, "trigger_run", {"collector_id": collector["id"]})
        assert "RUN_ALREADY_ACTIVE" in error_text(active)

        run_summary = result_payload(await call_tool(session, "get_run", {"run_id": started["runId"]}))
        assert run_summary["status"] == "queued"
        assert run_summary["integrityStatus"] == "verified"
        assert run_summary["ruleVersion"] == collector["activeRuleVersion"]
        assert run_summary["executionMode"] == "initial"

        missing_run = await call_tool(session, "get_run", {"run_id": "run_missing"})
        assert "RUN_NOT_FOUND" in error_text(missing_run)

        detail = result_payload(await call_tool(session, "get_collector", {"collector_id": collector["id"]}))
        assert detail["sourceUrl"] == "https://example.com/list"
        assert detail["activeRule"]["ruleVersion"] == collector["activeRuleVersion"]
        assert {"title", "buyer", "publishedAt", "budget"} <= {field["key"] for field in detail["activeRule"]["fields"]}
        assert detail["recentRuns"][0]["id"] == started["runId"]
        assert detail["sinks"] == []

        missing_collector = await call_tool(session, "get_collector", {"collector_id": "collector_missing"})
        assert "COLLECTOR_NOT_FOUND" in error_text(missing_collector)

    run = store.get_run(started["runId"])
    assert run["ruleAttestationId"]
    attestation = store.latest_rule_attestation(collector["activeRuleVersion"])
    assert attestation and run["ruleAttestationId"] == attestation["attestationId"]
    job = store.claim_job(60)
    assert job and job["payload"]["integrity"]["attestationId"] == attestation["attestationId"]
    assert job["payload"]["runId"] == started["runId"]


async def test_list_collectors_reports_active_rule_version(store: Store) -> None:
    seed_published_collector(store)
    async with create_connected_server_and_client_session(mcp_server.build_server()) as session:
        payload = result_payload(await call_tool(session, "list_collectors"))
    assert payload["count"] == 1
    summary = payload["collectors"][0]
    assert summary["activeRuleVersion"] and summary["activeRuleVersion"].endswith("_v1")
    assert summary["lastRun"] is None


class RecordingApp:
    def __init__(self) -> None:
        self.scopes: list[dict[str, Any]] = []

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        self.scopes.append(scope)


async def _drive_asgi(app: BearerTokenMiddleware, scope: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages


async def test_bearer_token_middleware_rejects_missing_or_wrong_token(store: Store) -> None:
    inner = RecordingApp()
    middleware = BearerTokenMiddleware(inner, "secret-token")
    base_headers = [(b"host", b"127.0.0.1:8818")]

    messages = await _drive_asgi(middleware, {"type": "http", "method": "POST", "path": "/mcp", "headers": base_headers})
    assert inner.scopes == []
    assert messages[0]["status"] == 401
    assert (b"www-authenticate", b'Bearer realm="extrio-mcp"') in messages[0]["headers"]
    assert b"missing or invalid bearer token" in messages[1]["body"]

    wrong = await _drive_asgi(
        middleware, {"type": "http", "method": "POST", "path": "/mcp", "headers": [*base_headers, (b"authorization", b"Bearer wrong")]}
    )
    assert wrong[0]["status"] == 401
    assert inner.scopes == []

    allowed = await _drive_asgi(
        middleware,
        {"type": "http", "method": "POST", "path": "/mcp", "headers": [*base_headers, (b"authorization", b"Bearer secret-token")]},
    )
    assert allowed == []
    assert len(inner.scopes) == 1

    await middleware({"type": "lifespan", "asgi.receive": None, "asgi.send": None}, None, None)
    assert len(inner.scopes) == 2
