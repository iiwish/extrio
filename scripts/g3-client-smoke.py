#!/usr/bin/env python3
"""Exercise real authenticated HTTP and MCP stdio against an isolated QA instance."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def save_credentials(path, credentials):
    with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as handle:
        json.dump(credentials, handle)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--api", required=True)
    args = parser.parse_args()
    root = args.instance.resolve()
    if not root.name.startswith("g3-qa-") or not args.api.startswith(
        "http://127.0.0.1:"
    ):
        parser.error("Only an explicitly named local g3-qa- instance is supported")
    os.environ.update(
        EXTRIO_DATABASE_URL="",
        EXTRIO_DATABASE_PATH=str(root / "extrio.db"),
        EXTRIO_ARTIFACT_PATH=str(root / "artifacts"),
        EXTRIO_SIGNING_PRIVATE_KEY_PATH=str(root / "keys/dev-rule-signing-key.pem"),
        EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH=str(
            root / "keys/dev-credential-encryption.key"
        ),
        EXTRIO_ALLOW_HTTP_LOCALHOST="true",
        EXTRIO_SEED_DEMO="false",
    )
    from benchmark import build_gather_spec, setup_collectors
    from extrio.app import persist_published_rule, store
    from extrio.contracts import sha256_digest

    async with httpx.AsyncClient(base_url=args.api + "/api/v1", timeout=30) as client:
        assert (await client.get("/collectors")).status_code == 401
        if (await client.get("/auth/state")).json()["setupRequired"]:
            credentials = {
                "username": "g3-qa-admin",
                "password": secrets.token_urlsafe(24),
            }
            await asyncio.to_thread(
                save_credentials, root / "qa-login.json", credentials
            )
            result = await client.post(
                "/auth/setup", json={**credentials, "displayName": "G3 QA"}
            )
        else:
            credentials = json.loads((root / "qa-login.json").read_text())
            result = await client.post("/auth/login", json=credentials)
        result.raise_for_status()
        existing = store.list_collectors()
        if not existing:
            collector_id = setup_collectors(1, args.api + "/demo/tenders", "127.0.0.1")[
                0
            ]
            bad = store.create_collector(
                "G3 inaccessible source",
                "Local 404 diagnostic fixture",
                args.api + "/demo/not-found",
                "127.0.0.1",
            )
            spec = build_gather_spec(bad["id"], bad["sourceUrl"], "127.0.0.1")
            bad["candidate"] = {
                "id": "candidate_g3_failure",
                "digest": sha256_digest(spec),
                "mode": "list_detail",
                "gatherSpec": spec,
            }
            persist_published_rule(
                bad,
                rule_version_id="rv_g3_failure",
                review_decisions={"ruleReviewer": "approved"},
                request_id="g3_qa",
                actor_id="g3_qa_operator",
            )
        else:
            assert len(existing) == 2 and {
                c["activeRuleVersion"] for c in existing
            } == {"rv_benchmark_001", "rv_g3_failure"}
            collector_id = next(
                c["id"]
                for c in existing
                if c["activeRuleVersion"] == "rv_benchmark_001"
            )
            bad = next(c for c in existing if c["activeRuleVersion"] == "rv_g3_failure")
        failed = await client.post(
            f"/collectors/{bad['id']}/runs",
            json={},
            headers={"Idempotency-Key": "g3-qa-failure-run"},
        )
        failed.raise_for_status()
        async with stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "extrio.mcp_server"],
                env=dict(os.environ),
            )
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 7

                async def call(name, payload=None):
                    result = await session.call_tool(name, payload or {})
                    assert not result.isError, result.content
                    return result.structuredContent

                assert (await call("list_collectors"))["count"] == 2
                assert (await call("get_collector", {"collector_id": collector_id}))[
                    "activeRule"
                ]
                started = await call("trigger_run", {"collector_id": collector_id})
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    run = await call("get_run", {"run_id": started["runId"]})
                    if run["status"] not in ("queued", "running", "finalizing"):
                        break
                    await asyncio.sleep(0.5)
                assert run["status"] == "succeeded", run
                first = await call(
                    "query_items", {"collector_id": collector_id, "limit": 2}
                )
                assert first["count"] == 2 and first["nextCursor"]
                second = await call(
                    "query_items",
                    {
                        "collector_id": collector_id,
                        "limit": 2,
                        "cursor": first["nextCursor"],
                    },
                )
                assert (
                    len({item["id"] for item in first["items"] + second["items"]}) == 4
                )
                item = await call("get_item", {"item_id": first["items"][0]["id"]})
                assert item["lineage"]["runId"] == started["runId"]
                evidence = await client.get(f"/runs/{started['runId']}/evidence")
                evidence.raise_for_status()
                report = {
                    "collectorId": collector_id,
                    "runId": started["runId"],
                    "mcpTools": len(tools.tools),
                    "items": 4,
                    "runStatus": run["status"],
                    "evidence": evidence.json(),
                }
        assert (await client.post("/auth/logout")).status_code == 200
        assert (await client.get("/collectors")).status_code == 401
        (root / "client-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
