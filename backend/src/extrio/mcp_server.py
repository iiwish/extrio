"""Extrio MCP server: governed data collection for AI agents.

Exposes the Extrio control plane over the Model Context Protocol so agents
(Claude Code, Cursor, DeepSeek, Doubao, ...) can operate an Extrio instance
directly. The server shares the exact same store the API and worker processes
use (``EXTRIO_DATABASE_URL`` / ``EXTRIO_DATABASE_PATH`` via
:func:`extrio.config.get_settings`); it never keeps a private database.

Governance model, in contrast to generic scraping MCPs:

- ``create_collection`` is an engineer-equivalent action that lands the new
  collector in the human review queue. The AI-compiled candidate rule is NOT
  published and no data is collected until a human reviewer approves and
  publishes it through the console/API.
- ``trigger_run`` executes an already-published, integrity-verified frozen
  rule. Runs are deterministic: no LLM is involved at runtime.
- Items read back by agents carry the attested rule version, run, and artifact
  lineage that produced them.

Transports:

- ``stdio`` (default): local, trusted single-user use.
- ``streamable HTTP``: enabled only when ``EXTRIO_MCP_TOKEN`` is set; every
  request must present ``Authorization: Bearer <EXTRIO_MCP_TOKEN>``. The token
  itself is never returned by any tool or log line.
"""

import argparse
import os
import secrets
import sys
import uuid
from typing import Any

import anyio.to_thread
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from starlette.types import ASGIApp, Receive, Scope, Send

from extrio import app as control_plane
from extrio.security import SourceUrlError, normalize_source_url
from extrio.store import InvalidCursor, Store, stable_id

GOVERNANCE_REVIEW_MESSAGE = (
    "Collection created and exploration queued; the rule requires human review before any data is collected."
)
RUN_STARTED_MESSAGE = (
    "Run queued against the collector's published, integrity-verified frozen rule. "
    "Execution is deterministic; no LLM is involved at runtime. Poll get_run for progress."
)
ALLOWED_DECISIONS = ("accepted", "rejected")
MAX_QUERY_LIMIT = 200
RECENT_RUNS_LIMIT = 5

SERVER_INSTRUCTIONS = (
    "Extrio turns a collection intent into a human-reviewed GatherSpec rule, publishes an "
    "Ed25519-attested immutable rule, and executes it as a deterministic collection run.\n"
    "Governance: create_collection queues AI exploration but the candidate rule requires human "
    "review before publication; trigger_run only executes already-published frozen rules "
    "(no LLM at runtime). Data returned by these tools is attested: every item carries the rule "
    "version, run, and artifact lineage that produced it.\n"
    "Typical loop: list_collectors -> get_collector -> trigger_run -> get_run -> query_items/get_item. "
    "create_collection submits a new governed source for human review."
)


class BearerTokenMiddleware:
    """Minimal ASGI middleware enforcing a static bearer token on HTTP requests.

    Used to guard the FastMCP streamable-HTTP app when ``EXTRIO_MCP_TOKEN`` is
    configured. Non-HTTP scopes (e.g. lifespan) pass through untouched. On
    success the request is forwarded unchanged; the token value itself is never
    logged or echoed.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"authorization", b"")
        if not secrets.compare_digest(supplied, self._expected):
            body = b'{"code": "UNAUTHORIZED", "message": "missing or invalid bearer token"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"www-authenticate", b'Bearer realm="extrio-mcp"'),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def shared_store() -> Store:
    """Resolve the control-plane store lazily.

    ``control_plane.store`` is read on every call (never bound at import time)
    so the MCP server always sees the store instance the API module uses,
    including test runs that swap it.
    """

    return control_plane.store


def _error(code: str, message: str) -> ToolError:
    return ToolError(f"{code}: {message}")


def _rule_field_summary(spec: dict[str, Any]) -> list[dict[str, Any]]:
    collect = spec.get("collect") or {}
    stage = collect.get("detail") or collect.get("list") or {}
    field_specs = stage.get("fields") or {}
    return [{"key": key, "required": bool(field.get("required"))} for key, field in field_specs.items()]


def list_collectors_summary(store: Store) -> dict[str, Any]:
    """Summaries for every collector, ordered newest first."""

    runs = {run["id"]: run for run in store.list_runs()}
    collectors = []
    for collector in store.list_collectors():
        run = runs.get(collector.get("latestRunId") or "")
        schedule = collector.get("schedule") or {}
        collectors.append(
            {
                "id": collector["id"],
                "name": collector["name"],
                "status": collector["status"],
                "sourceHost": collector["sourceHost"],
                "activeRuleVersion": collector.get("activeRuleVersion"),
                "scheduleEnabled": bool(schedule.get("enabled")),
                "lastRun": None
                if run is None
                else {
                    "id": run["id"],
                    "status": run.get("status"),
                    "startedAt": run.get("startedAtIso"),
                    "duration": run.get("duration"),
                    "acceptedCount": run.get("acceptedCount", 0),
                    "rejectedCount": run.get("rejectedCount", 0),
                },
            }
        )
    return {"collectors": collectors, "count": len(collectors)}


def get_collector_detail(store: Store, collector_id: str) -> dict[str, Any]:
    """Full collector detail: source, rule summary, recent runs, sinks."""

    collector = store.get_collector(collector_id)
    if collector is None:
        raise _error("COLLECTOR_NOT_FOUND", f"collector {collector_id} does not exist")
    rule_version_record = store.get_rule_version(collector["activeRuleVersion"]) if collector.get("activeRuleVersion") else None
    spec = (rule_version_record or {}).get("gatherSpec") or (collector.get("candidate") or {}).get("gatherSpec") or {}
    rule_summary = None
    if collector.get("activeRuleVersion"):
        rule_summary = {
            "ruleVersion": collector["activeRuleVersion"],
            "ruleDigest": (spec.get("integrity") or {}).get("ruleDigest"),
            "mode": (collector.get("candidate") or {}).get("mode"),
            "fields": _rule_field_summary(spec),
        }
    recent_runs = [
        {
            "id": run["id"],
            "status": run.get("status"),
            "acceptedCount": run.get("acceptedCount", 0),
            "rejectedCount": run.get("rejectedCount", 0),
            "duration": run.get("duration"),
            "startedAt": run.get("startedAtIso"),
        }
        for run in store.list_runs()
        if run.get("collectorId") == collector_id
    ][:RECENT_RUNS_LIMIT]
    return {
        "id": collector["id"],
        "name": collector["name"],
        "status": collector["status"],
        "intent": collector["intent"],
        "sourceUrl": collector["sourceUrl"],
        "sourceHost": collector["sourceHost"],
        "collectionId": collector.get("collectionId"),
        "collectionName": collector.get("collectionName"),
        "activeRuleVersion": collector.get("activeRuleVersion"),
        "activeRule": rule_summary,
        "activeOperationId": collector.get("activeOperationId"),
        "checkpoint": store.get_checkpoint(collector_id),
        "schedule": collector.get("schedule"),
        "recentRuns": recent_runs,
        "sinks": store.list_sinks_for_collector(collector_id),
    }


def query_items_page(
    store: Store,
    collector_id: str | None,
    decision: str | None,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """Deterministic page of collected items with optional filters."""

    if not 1 <= limit <= MAX_QUERY_LIMIT:
        raise _error("VALIDATION_FAILED", f"limit must be between 1 and {MAX_QUERY_LIMIT}")
    if decision is not None and decision not in ALLOWED_DECISIONS:
        raise _error("VALIDATION_FAILED", f"decision must be one of {list(ALLOWED_DECISIONS)}")
    if collector_id is not None and store.get_collector(collector_id) is None:
        raise _error("COLLECTOR_NOT_FOUND", f"collector {collector_id} does not exist")
    try:
        result = store.list_items_cursor(collector_id=collector_id, decision=decision, limit=limit, cursor=cursor)
    except InvalidCursor as exc:
        raise _error("INVALID_CURSOR", "cursor is invalid; pass the nextCursor value from the previous page") from exc
    items = [
        {
            "id": item["id"],
            "collectorId": item.get("collectorId"),
            "collectorName": item.get("collectorName"),
            "title": item.get("title"),
            "entityKey": item.get("entityKey"),
            "publishedAt": item.get("publishedAt"),
            "observedAt": item.get("observedAt"),
            "sourceUrl": item.get("sourceUrl"),
            "decision": item.get("decision"),
            "changeType": item.get("changeType"),
            "extractedData": item.get("extractedData"),
        }
        for item in result["items"]
    ]
    return {"items": items, "count": len(items), "nextCursor": result["nextCursor"]}


def get_item_record(store: Store, item_id: str) -> dict[str, Any]:
    """Full item record including extractedData, lineage, and observations."""

    item = store.get_item(item_id)
    if item is None:
        raise _error("ITEM_NOT_FOUND", f"item {item_id} does not exist")
    return item


def trigger_collector_run(collector_id: str) -> dict[str, Any]:
    """Start a run through the exact API code path (create_run_operation)."""

    try:
        with control_plane.mutation_lock:
            operation = control_plane.create_run_operation(collector_id)
    except control_plane.RunStartError as exc:
        raise _error(exc.code, str(exc)) from None
    return {
        "runId": operation["resourceId"],
        "operationId": operation["id"],
        "status": operation["status"],
        "statusUrl": operation["statusUrl"],
        "message": RUN_STARTED_MESSAGE,
    }


def create_collection_with_exploration(store: Store, name: str, intent: str, entry_url: str) -> dict[str, Any]:
    """Create a collector (engineer-equivalent) and enqueue rule exploration.

    Mirrors the API's collector POST route validation and the exploration
    enqueue path, but never publishes a rule: the collector enters the human
    review queue until a reviewer approves the AI-compiled candidate rule.
    """

    collection_name = str(name).strip()
    collection_intent = str(intent).strip()
    if not collection_name or not collection_intent:
        raise _error("VALIDATION_FAILED", "name and intent must not be empty")
    settings = control_plane.settings
    try:
        source_url, source_host = normalize_source_url(
            str(entry_url),
            allow_http_localhost=settings.allow_http_localhost,
            allow_http_public=settings.allow_http_public,
        )
    except SourceUrlError as exc:
        raise _error(exc.code, str(exc)) from None
    if store.source_exists(source_url):
        raise _error("SOURCE_ALREADY_EXISTS", f"a collector for source URL {source_url} already exists")
    collector = store.create_collector(
        collection_name,
        collection_intent,
        source_url,
        source_host,
        collection_id=stable_id("collection", uuid.uuid4().hex, 40),
        collection_name=collection_name,
    )
    ai_run_id = stable_id("ai_run", uuid.uuid4().hex, 32)
    operation = store.create_async_command(
        kind="explore",
        collector_id=collector["id"],
        resource_type="collector",
        resource_id=collector["id"],
        job_payload={"collectorId": collector["id"], "previousStatus": collector["status"], "aiRunId": ai_run_id},
        collector_changes={"status": "exploring", "updatedAt": "刚刚"},
        ai_run={
            "id": ai_run_id,
            "collectorId": collector["id"],
            "collectorName": collector["name"],
            "sourceUrl": collector["sourceUrl"],
            "kind": "rule_generation",
            "trigger": "initial_generation",
            "initiatedBy": "mcp_agent",
        },
    )
    return {
        "collectorId": collector["id"],
        "collectionId": collector["collectionId"],
        "name": collector["name"],
        "sourceUrl": collector["sourceUrl"],
        "sourceHost": collector["sourceHost"],
        "status": "exploring",
        "operationId": operation["id"],
        "aiRunId": ai_run_id,
        "message": GOVERNANCE_REVIEW_MESSAGE,
    }


def get_run_summary(store: Store, run_id: str) -> dict[str, Any]:
    """Run record summary: status, counts, stop reason, integrity, checkpoint."""

    run = store.get_run(run_id)
    if run is None:
        raise _error("RUN_NOT_FOUND", f"run {run_id} does not exist")
    summary_keys = (
        "id",
        "operationId",
        "collectorId",
        "collectorName",
        "status",
        "acceptedCount",
        "rejectedCount",
        "newItems",
        "updatedItems",
        "unchangedItems",
        "pagesFetched",
        "listPagesFetched",
        "detailUrlsDiscovered",
        "detailPagesFetched",
        "recordsOutsideWindow",
        "paginationStopReason",
        "ruleVersion",
        "ruleDigest",
        "ruleAttestationId",
        "signingKeyId",
        "trustRevision",
        "integrityStatus",
        "executionMode",
        "windowStart",
        "duration",
        "summary",
        "recoveryAction",
    )
    summary = {key: run.get(key) for key in summary_keys}
    summary["startedAt"] = run.get("startedAtIso")
    summary["checkpointAfter"] = run.get("checkpointAfter")
    return summary


def build_server(*, host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    """Build the FastMCP server with the seven governed tools registered."""

    server = FastMCP(name="extrio", instructions=SERVER_INSTRUCTIONS, host=host, port=port)

    @server.tool()
    async def list_collectors() -> dict[str, Any]:
        """List all collectors with summaries.

        Returns id, name, status, sourceHost, active rule version, schedule enabled, and the last
        run outcome (status, started time, accepted/rejected counts).
        """

        return await anyio.to_thread.run_sync(list_collectors_summary, shared_store())

    @server.tool()
    async def get_collector(collector_id: str) -> dict[str, Any]:
        """Get one collector in detail: source entry URL, intent, active rule summary, recent runs, checkpoint, schedule, and sinks.

        The active rule summary carries the published rule version, its digest, and the extracted
        fields from the frozen GatherSpec. Recent runs cover the last 5 runs with counts and
        durations. Sink URLs are included; sink secrets are never returned.
        """

        return await anyio.to_thread.run_sync(get_collector_detail, shared_store(), collector_id)

    @server.tool()
    async def query_items(
        collector_id: str | None = None,
        decision: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Page through collected items in deterministic (observedAt DESC) order.

        Optionally filter by collector and quality decision ('accepted' or 'rejected'); pass the
        nextCursor value from the previous page to continue. Items include extractedData plus
        attested lineage metadata (rule version, run, artifact) proving where the data came from.
        """

        return await anyio.to_thread.run_sync(query_items_page, shared_store(), collector_id, decision, limit, cursor)

    @server.tool()
    async def get_item(item_id: str) -> dict[str, Any]:
        """Get the full record for one collected item.

        Includes extractedData, decision and rejection evidence, observation history, and the
        lineage (source revision, rule version, run, artifact) that produced it.
        """

        return await anyio.to_thread.run_sync(get_item_record, shared_store(), item_id)

    @server.tool()
    async def trigger_run(collector_id: str) -> dict[str, Any]:
        """Start a collection run for a collector.

        GOVERNANCE: runs execute the collector's already-published, integrity-verified frozen rule
        — deterministic, no LLM at runtime. Fails with RUN_ALREADY_ACTIVE if a run is already in
        progress, RULE_NOT_PUBLISHED when no reviewed rule has been published, and integrity
        errors if the attestation no longer verifies.
        """

        return await anyio.to_thread.run_sync(trigger_collector_run, collector_id)

    @server.tool()
    async def create_collection(name: str, intent: str, entry_url: str) -> dict[str, Any]:
        """Create a new collection (name, intent, HTTPS entry URL).

        This engineer-equivalent action registers the source and queues an AI exploration that
        compiles a candidate rule. GOVERNANCE: the collector lands in the human review queue —
        the candidate rule requires human review and publication before ANY data is collected;
        agents cannot publish rules through this tool.
        """

        return await anyio.to_thread.run_sync(create_collection_with_exploration, shared_store(), name, intent, entry_url)

    @server.tool()
    async def get_run(run_id: str) -> dict[str, Any]:
        """Get one collection run.

        Includes status, accepted/rejected counts, pagination stop reason, execution mode and
        window, integrity verification status (rule digest, attestation, signing key), and
        checkpoint progress.
        """

        return await anyio.to_thread.run_sync(get_run_summary, shared_store(), run_id)

    return server


def run() -> None:
    """Console entry point for ``extrio-mcp``."""

    parser = argparse.ArgumentParser(
        prog="extrio-mcp",
        description="Extrio MCP server: governed data collection for AI agents.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio for local trusted use (default); http for streamable HTTP secured by EXTRIO_MCP_TOKEN",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address for the http transport")
    parser.add_argument("--port", type=int, default=8818, help="bind port for the http transport")
    args = parser.parse_args()

    if args.transport == "stdio":
        build_server().run(transport="stdio")
        return

    token = os.environ.get("EXTRIO_MCP_TOKEN", "").strip()
    if not token:
        parser.exit(
            2,
            "extrio-mcp: the http transport requires EXTRIO_MCP_TOKEN to be set; "
            "refusing to serve unauthenticated MCP over HTTP\n",
        )
    server = build_server(host=args.host, port=args.port)
    uvicorn.run(BearerTokenMiddleware(server.streamable_http_app(), token), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(run())
