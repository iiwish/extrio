#!/usr/bin/env python3
"""Offline benchmark harness for the Extrio collection pipeline.

Creates temporary collectors against the bundled local demo source, publishes a
fixed hand-written GatherSpec (no LLM involved), executes deterministic
collection runs through the real worker path, and prints a summary plus a
markdown block for docs/benchmarks.md.

Usage:
    uv run --project backend python scripts/benchmark.py --collectors 3 --pages 2

Isolation: the harness runs against a temporary SQLite database and temporary
artifact/key directories (EXTRIO_DATABASE_URL and friends), and serves the demo
source from an in-process uvicorn server bound to 127.0.0.1 on an ephemeral
port. No external network access and no writes to a real deployment. Every run
must finish in the succeeded terminal state, otherwise the harness exits
non-zero.
"""

import argparse
import asyncio
import os
import platform
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the Extrio deterministic run pipeline against the local demo source.")
    parser.add_argument("--collectors", type=int, default=3, help="Number of temporary collectors to create (N).")
    parser.add_argument("--pages", type=int, default=2, help="Number of collection runs executed per collector (M).")
    args = parser.parse_args()
    if args.collectors < 1 or args.pages < 1:
        parser.error("--collectors and --pages must be >= 1")
    return args


def configure_environment(workdir: Path) -> None:
    """Point Extrio at throwaway storage before any extrio module is imported."""
    os.environ["EXTRIO_DATABASE_URL"] = f"sqlite:///{workdir / 'benchmark.db'}"
    os.environ["EXTRIO_ARTIFACT_PATH"] = str(workdir / "artifacts")
    os.environ["EXTRIO_SIGNING_PRIVATE_KEY_PATH"] = str(workdir / "keys" / "bench-rule-signing-key.pem")
    os.environ["EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH"] = str(workdir / "keys" / "bench-credential-encryption.key")


def start_demo_server() -> tuple[uvicorn.Server, int]:
    """Serve only the bundled demo router on 127.0.0.1 with an ephemeral port."""
    from extrio.demo import router as demo_router

    app = FastAPI()
    app.include_router(demo_router)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(240):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("demo source server failed to start")
    port = int(server.servers[0].sockets[0].getsockname()[1])
    return server, port


def build_gather_spec(collector_id: str, entrypoint: str, host: str) -> dict[str, Any]:
    """Hand-written fixed rule for the demo source, modeled on docs/contracts/gather-spec.example.json.

    Deterministic by construction: identical inputs always produce the same
    GatherSpec and therefore the same rule digest. finalize_rule_spec() fixes
    ruleVersionId and the integrity digest at publication time.
    """
    return {
        "schemaVersion": "extrio.gather.v1",
        "ruleVersionId": "rv_benchmark_placeholder",
        "tenantId": "tenant_demo",
        "collectorId": collector_id,
        "collectionVersionRef": {
            "collectionId": "collection_nationwide_tender",
            "collectionVersionId": "collection_version_001",
            "version": "1.0",
        },
        "sourceRevisionRef": {
            "sourceId": "source_benchmark_demo",
            "sourceRevisionId": "source_revision_001",
            "configDigest": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        },
        "templateRef": {
            "templateId": "template_tender_notice",
            "templateVersionId": "template_version_001",
            "version": "1.0",
        },
        "compiler": {
            "name": "extrio-benchmark",
            "version": "1.0.0",
            "compiledAt": "2026-09-03T00:00:00Z",
            "inputDigest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
            "overrideRefs": [],
            "agent": {
                "provider": "benchmark",
                "model": "hand-written-gather-spec",
                "promptVersion": "benchmark",
                "toolchainVersion": "benchmark",
            },
        },
        "runtimeCompatibility": {
            "runtimeName": "extrio-python",
            "minVersion": "0.2.0",
            "maxVersionExclusive": "0.4.0",
            "dialectVersion": "1.0",
            "parserVersion": "1.0",
            "tzdbVersion": "2026a",
            "unicodeVersion": "17.0",
        },
        "contract": {
            "identityFields": ["detailUrl"],
            "fingerprintFields": ["title", "contentHtml", "publishAt"],
            "outputContractDigest": "sha256:3d03c545fa9fb03285848b33459d08979de0604a7e5b3b1d5d5aad8de2b115bc",
            "normalizedItemSchema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "detailUrl": {"type": "string", "format": "uri"},
                    "listTitle": {"type": "string"},
                    "listPublishedAt": {"type": ["string", "null"], "format": "date-time"},
                    "title": {"type": "string", "minLength": 1},
                    "contentHtml": {"type": "string"},
                    "buyer": {"type": ["string", "null"]},
                    "region": {"type": ["string", "null"]},
                    "budgetAmount": {"type": ["number", "null"]},
                    "publishAt": {"type": "string", "format": "date-time"},
                },
                "required": ["detailUrl", "title", "contentHtml", "publishAt"],
                "additionalProperties": False,
            },
            "quality": {
                "requiredFieldCompleteness": 0.95,
                "maxItemErrorRatio": 0.05,
                "emptyResultPolicy": "suspect",
            },
        },
        "sourceContext": {
            "entrypoints": [entrypoint],
            "allowedHosts": [host],
            "transport": "http",
            "rateLimit": {"rps": 2, "burst": 4, "maxConcurrency": 2},
            "requestPolicy": {
                "userAgent": "Extrio/Benchmark 0.4",
                "timeoutMs": 30000,
                "maxResponseBytes": 20971520,
                "maxRedirects": 3,
            },
        },
        "collect": {
            "list": {
                "request": {"entrypointIndex": 0, "method": "GET", "headers": {"Accept": "text/html,application/xhtml+xml"}, "query": {}},
                "responseType": "html",
                "itemsSelector": "css:ul.notice-list li",
                "fields": {
                    "detailUrl": {
                        "selector": "css:a.notice-title::attr(href)",
                        "valueType": "url",
                        "required": True,
                        "onError": "reject_item",
                        "multipleMatchPolicy": "error",
                        "transforms": ["trim", "absolute_url"],
                    },
                    "listTitle": {
                        "selector": "css:a.notice-title::text",
                        "valueType": "string",
                        "required": False,
                        "onError": "null",
                        "multipleMatchPolicy": "first",
                        "transforms": ["trim"],
                    },
                    "listPublishedAt": {
                        "selector": "css:time::attr(datetime)",
                        "valueType": "datetime",
                        "required": False,
                        "onError": "null",
                        "multipleMatchPolicy": "first",
                        "transforms": ["trim"],
                        "datetimeFormat": "RFC3339",
                        "defaultTimezone": "Asia/Shanghai",
                    },
                },
                "pagination": {
                    "type": "page",
                    "parameter": "page",
                    "location": "query",
                    "start": 1,
                    "step": 1,
                    "maxPages": 3,
                    "stopWhenNoItems": True,
                },
            },
            "detail": {
                "request": {"urlTemplate": "{{detailUrl}}", "method": "GET", "headers": {"Accept": "text/html,application/xhtml+xml"}},
                "responseType": "html",
                "fields": {
                    "title": {
                        "label": "公告标题",
                        "selector": "css:h1.notice-title::text",
                        "valueType": "string",
                        "required": True,
                        "onError": "reject_item",
                        "multipleMatchPolicy": "error",
                        "transforms": ["trim", "collapse_whitespace"],
                    },
                    "contentHtml": {
                        "selector": "css:div.notice-content::html",
                        "valueType": "html",
                        "required": True,
                        "onError": "reject_item",
                        "multipleMatchPolicy": "error",
                    },
                    "buyer": {
                        "label": "采购单位",
                        "selector": "css:[data-field='buyer']::text",
                        "valueType": "string",
                        "required": False,
                        "onError": "null",
                        "multipleMatchPolicy": "first",
                        "transforms": ["trim"],
                    },
                    "region": {
                        "label": "所属区域",
                        "selector": "css:[data-field='region']::text",
                        "valueType": "string",
                        "required": False,
                        "onError": "null",
                        "multipleMatchPolicy": "first",
                        "transforms": ["trim"],
                    },
                    "budgetAmount": {
                        "label": "预算金额",
                        "selector": "css:.notice-budget .amount::text",
                        "valueType": "number",
                        "required": False,
                        "onError": "null",
                        "multipleMatchPolicy": "first",
                        "transforms": ["trim", {"type": "regex_extract", "pattern": "[0-9][0-9,]*(?:\\.[0-9]+)?", "group": 0}],
                    },
                    "publishAt": {
                        "label": "发布时间",
                        "selector": "css:div.meta time::attr(datetime)",
                        "valueType": "datetime",
                        "required": True,
                        "onError": "reject_item",
                        "multipleMatchPolicy": "error",
                        "transforms": ["trim"],
                        "datetimeFormat": "RFC3339",
                        "defaultTimezone": "Asia/Shanghai",
                    },
                },
            },
            "requestRetry": {"maxAttempts": 3, "initialDelayMs": 500, "maxDelayMs": 5000},
            "budget": {
                "maxPages": 3,
                "maxItems": 10000,
                "maxDurationSeconds": 3600,
                "maxTotalBytes": 1073741824,
                "onExceeded": "partial",
            },
        },
        "output": {
            "rawRetentionDays": 30,
            "emitUnchanged": False,
            "sinks": [
                {
                    "sinkId": "sink_benchmark_webhook",
                    "sinkVersionId": "sink_version_benchmark_001",
                    "type": "webhook",
                    "eventMode": "upsert",
                    "deliveryPolicy": {
                        "maxAttempts": 8,
                        "initialDelaySeconds": 5,
                        "maxDelaySeconds": 21600,
                        "timeoutSeconds": 30,
                        "totalWindowSeconds": 172800,
                    },
                }
            ],
        },
        "integrity": {"digestAlgorithm": "sha256", "ruleDigest": "sha256:0000000000000000000000000000000000000000000000000000000000000000"},
    }


@dataclass
class RunSample:
    collector_index: int
    run_index: int
    run_id: str
    status: str
    stop_reason: str
    pages: int
    list_pages: int
    detail_pages: int
    accepted: int
    rejected: int
    new_items: int
    updated_items: int
    unchanged_items: int
    duration_seconds: float


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = max(1, min(len(ordered), round(ratio * len(ordered))))
    return ordered[rank - 1]


def setup_collectors(collector_count: int, entrypoint: str, host: str) -> list[str]:
    """Create collectors, attach the fixed rule, and publish it (bypassing the LLM)."""
    from extrio.app import persist_published_rule, store
    from extrio.contracts import sha256_digest

    store.initialize()
    collector_ids: list[str] = []
    for index in range(1, collector_count + 1):
        collector = store.create_collector(
            f"基准采集器 {index:03d}",
            "采集演示源的公开招标公告，提取项目名称、采购单位、发布日期、预算和详情链接。",
            entrypoint,
            host,
        )
        spec = build_gather_spec(collector["id"], entrypoint, host)
        collector["candidate"] = {
            "id": f"candidate_benchmark_{index:03d}",
            "digest": sha256_digest(spec),
            "mode": "list_detail",
            "gatherSpec": spec,
        }
        result = persist_published_rule(
            collector,
            rule_version_id=f"rv_benchmark_{index:03d}",
            review_decisions={"ruleReviewer": "approved"},
            request_id="benchmark_setup",
            actor_id="user_benchmark",
        )
        collector_ids.append(result["collectorId"] if "collectorId" in result else collector["id"])
    return collector_ids


async def execute_runs(collector_ids: list[str], runs_per_collector: int) -> list[RunSample]:
    import logging

    from extrio.app import create_run_operation, store
    from extrio.worker import Worker

    # The worker configures root INFO logging at import time; keep crawlee's
    # per-crawl statistics out of the benchmark output.
    logging.getLogger().setLevel(logging.WARNING)
    for noisy in ("crawlee", "ParselCrawler", "extrio.worker"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    worker = Worker()
    samples: list[RunSample] = []
    for collector_index, collector_id in enumerate(collector_ids, start=1):
        for run_index in range(1, runs_per_collector + 1):
            operation = create_run_operation(collector_id)
            run_id = str(operation["resourceId"])
            run = store.get_run(run_id)
            if run is None:
                raise RuntimeError(f"run {run_id} was not persisted by create_run_operation")
            job = {
                "operationId": operation["id"],
                "kind": "run",
                "payload": {
                    "collectorId": collector_id,
                    "runId": run_id,
                    "integrity": {
                        "ruleVersionId": run["ruleVersion"],
                        "attestationId": run["ruleAttestationId"],
                        "ruleDigest": run["ruleDigest"],
                        "keyId": run["signingKeyId"],
                        "trustRevision": run["trustRevision"],
                    },
                    "policyVersionId": run["policyVersion"],
                    "policyDigest": run["policyDigest"],
                    "checkpointBefore": run["checkpointBefore"],
                },
            }
            started = time.perf_counter()
            await worker.process(job)
            elapsed = time.perf_counter() - started
            finished = store.get_run(run_id)
            if finished is None:
                raise RuntimeError(f"run {run_id} disappeared after processing")
            samples.append(
                RunSample(
                    collector_index=collector_index,
                    run_index=run_index,
                    run_id=run_id,
                    status=str(finished["status"]),
                    stop_reason=str(finished["paginationStopReason"]),
                    pages=int(finished["pagesFetched"]),
                    list_pages=int(finished["listPagesFetched"]),
                    detail_pages=int(finished["detailPagesFetched"]),
                    accepted=int(finished["acceptedCount"]),
                    rejected=int(finished["rejectedCount"]),
                    new_items=int(finished["newItems"]),
                    updated_items=int(finished["updatedItems"]),
                    unchanged_items=int(finished["unchangedItems"]),
                    duration_seconds=elapsed,
                )
            )
    return samples


def render_markdown(args: argparse.Namespace, samples: list[RunSample], port: int, total_seconds: float) -> str:
    total_runs = len(samples)
    total_pages = sum(sample.pages for sample in samples)
    total_accepted = sum(sample.accepted for sample in samples)
    durations = [sample.duration_seconds for sample in samples]
    minutes = max(total_seconds / 60.0, 1e-9)
    lines = [
        "<!-- 以下数据块由 scripts/benchmark.py 实际运行生成，请勿手写数字。 -->",
        "",
        f"- 运行参数：`--collectors {args.collectors} --pages {args.pages}`（{args.collectors} 个采集器 × {args.pages} 次运行 = {total_runs} 次）",
        f"- 运行日期：{datetime.now(UTC).strftime('%Y-%m-%d')}",
        f"- 环境：Python {platform.python_version()} / {platform.platform()}",
        "- 存储：临时 SQLite（每次基准运行独立创建，结束后删除）",
        f"- 数据源：本机 demo 源 `http://127.0.0.1:{port}/demo/tenders`（进程内 uvicorn，无外部网络）",
        "",
        "| 采集器 | 运行 | 终态 | 停止原因 | 列表页 | 详情页 | 页面合计 | 接收 | 拒绝 | 变化（新增/更新/未变） | 耗时 (s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for sample in samples:
        lines.append(
            f"| {sample.collector_index} | {sample.run_index} | {sample.status} | {sample.stop_reason} | {sample.list_pages} "
            f"| {sample.detail_pages} | {sample.pages} | {sample.accepted} | {sample.rejected} "
            f"| {sample.new_items}/{sample.updated_items}/{sample.unchanged_items} | {sample.duration_seconds:.2f} |"
        )
    lines.append(
        f"| **合计** | | | | | | **{total_pages}** | **{total_accepted}** | **{sum(s.rejected for s in samples)}** | "
        f"**{sum(s.new_items for s in samples)}/{sum(s.updated_items for s in samples)}/{sum(s.unchanged_items for s in samples)}** "
        f"| **{total_seconds:.2f}** |"
    )
    lines.append("")
    lines.append(
        f"吞吐：**{total_pages / minutes:.0f} 页/分钟**、**{total_accepted / minutes:.0f} 接收 Item/分钟**；"
        f"单次运行耗时 p50 = **{percentile(durations, 0.50):.2f}s**、p95 = **{percentile(durations, 0.95):.2f}s**。"
    )
    return "\n".join(lines)


def render_text_summary(args: argparse.Namespace, samples: list[RunSample], total_seconds: float) -> str:
    total_runs = len(samples)
    total_pages = sum(sample.pages for sample in samples)
    total_accepted = sum(sample.accepted for sample in samples)
    durations = [sample.duration_seconds for sample in samples]
    minutes = max(total_seconds / 60.0, 1e-9)
    return (
        f"collectors={args.collectors} runs_per_collector={args.pages} total_runs={total_runs} "
        f"wall={total_seconds:.2f}s pages={total_pages} ({total_pages / minutes:.0f}/min) "
        f"accepted={total_accepted} ({total_accepted / minutes:.0f}/min) "
        f"p50={percentile(durations, 0.50):.2f}s p95={percentile(durations, 0.95):.2f}s"
    )


async def run_benchmark(args: argparse.Namespace, port: int) -> int:
    entrypoint = f"http://127.0.0.1:{port}/demo/tenders"
    host = "127.0.0.1"
    total_started = time.perf_counter()
    collector_ids = setup_collectors(args.collectors, entrypoint, host)
    samples = await execute_runs(collector_ids, args.pages)
    total_seconds = time.perf_counter() - total_started

    print("Extrio deterministic pipeline benchmark")
    print(f"  source      : {entrypoint} (in-process demo router, offline)")
    print(f"  collectors  : {args.collectors}   runs per collector: {args.pages}   total runs: {len(samples)}")
    print("  storage     : temporary sqlite + temporary artifacts (removed on exit)")
    print()
    print("collector  run  status                stop_reason            pages  list  detail  accepted  rejected  duration")
    for sample in samples:
        print(
            f"{sample.collector_index:<9}  {sample.run_index:<4} {sample.status:<20}  {sample.stop_reason:<20}  "
            f"{sample.pages:>5}  {sample.list_pages:>4}  {sample.detail_pages:>6}  {sample.accepted:>8}  {sample.rejected:>8}  "
            f"{sample.duration_seconds:>7.2f}s"
        )
    print()
    print(f"summary: {render_text_summary(args, samples, total_seconds)}")
    print()
    print("markdown block for docs/benchmarks.md:")
    print()
    print(render_markdown(args, samples, port, total_seconds))

    failures = [sample for sample in samples if sample.status != "succeeded"]
    if failures:
        print(f"\nFAILED: {len(failures)} run(s) did not reach the succeeded terminal state", file=sys.stderr)
        for sample in failures:
            print(f"  collector={sample.collector_index} run={sample.run_index} status={sample.status} stop={sample.stop_reason}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="extrio-benchmark-") as raw_dir:
        configure_environment(Path(raw_dir))
        server, port = start_demo_server()
        try:
            return asyncio.run(run_benchmark(args, port))
        finally:
            server.should_exit = True


if __name__ == "__main__":
    raise SystemExit(main())
