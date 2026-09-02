import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from extrio.contracts import ContractBundle, sha256_digest
from extrio.harvest import (
    build_candidate,
    build_candidate_from_plan,
    discover,
    discover_records_from_spec,
    embedded_list_url,
    looks_like_dynamic_list_shell,
    make_item,
)
from extrio.integrity import calculate_rule_digest
from extrio.model_gateway import ModelCompileError, ModelRuleCompiler

ProgressCallback = Callable[[str, int, dict[str, int]], Awaitable[None]]


class SourceFetchError(RuntimeError):
    code = "SOURCE_UNREACHABLE"
    retryable = True


def source_fetch_error(source_url: str, error_message: str) -> SourceFetchError:
    host = urlsplit(source_url).hostname or source_url
    normalized = error_message.casefold()
    if "err_name_not_resolved" in normalized or "name or service not known" in normalized:
        reason = "域名无法解析"
    elif "err_connection_refused" in normalized:
        reason = "目标站点拒绝了连接"
    elif "err_connection_closed" in normalized or "err_connection_reset" in normalized:
        reason = "目标站点在建立连接时关闭了连接"
    elif "timeout" in normalized or "timed out" in normalized:
        reason = "访问超时"
    elif "robots" in normalized:
        reason = "目标站点的 robots.txt 不允许采集"
    else:
        reason = "目标站点暂时无法访问"
    return SourceFetchError(f"无法访问 Source：{host}，{reason}。请确认网址可从当前运行环境访问，并检查网络或代理配置后重试。")


@dataclass
class ExplorationResult:
    candidate: dict[str, Any]
    preview_items: list[dict[str, Any]]
    metrics: dict[str, int]


class Crawl4AIExplorer:
    def __init__(
        self,
        contracts: ContractBundle,
        artifact_path: Path,
        model_compiler: ModelRuleCompiler | None = None,
    ):
        self.contracts = contracts
        self.artifact_path = artifact_path
        self.model_compiler = model_compiler

    async def explore(
        self,
        collector: dict[str, Any],
        operation_id: str,
        progress: ProgressCallback,
        ai_run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> ExplorationResult:
        artifact_dir = self.artifact_path / operation_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metrics = {
            "listPagesFetched": 0,
            "detailUrlsDiscovered": 0,
            "detailPagesFetched": 0,
            "recordsOutsideWindow": 0,
            "duplicateDetailUrls": 0,
            "newItems": 0,
            "updatedItems": 0,
            "unchangedItems": 0,
            "warningCount": 0,
        }
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            check_robots_txt=True,
            page_timeout=30_000,
            delay_before_return_html=3.0,
        )
        browser_config = BrowserConfig(headless=True, verbose=False)
        async with AsyncWebCrawler(config=browser_config) as crawler:
            await progress("fetching_list", 15, metrics)
            list_result = await crawler.arun(url=collector["sourceUrl"], config=config)
            if not list_result.success:
                raise source_fetch_error(collector["sourceUrl"], list_result.error_message)
            source_html = list_result.html
            requires_browser = looks_like_dynamic_list_shell(source_html)
            if requires_browser:
                settled_result = await crawler.arun(url=collector["sourceUrl"], config=config)
                if settled_result.success:
                    source_html = settled_result.html
            effective_url = collector["sourceUrl"]
            list_html = source_html
            detail_urls, _next_url = discover(list_html, effective_url)
            frame_url = embedded_list_url(source_html, collector["sourceUrl"]) if not detail_urls else None
            if frame_url:
                frame_result = await crawler.arun(url=frame_url, config=config)
                if not frame_result.success:
                    raise source_fetch_error(frame_url, frame_result.error_message)
                (artifact_dir / "source-shell.html").write_text(source_html, encoding="utf-8")
                effective_url = frame_url
                list_html = frame_result.html
                detail_urls, _next_url = discover(list_html, effective_url)
            (artifact_dir / "list-001.html").write_text(list_html, encoding="utf-8")
            metrics["listPagesFetched"] = 1
            rule_collector = {**collector, "sourceUrl": effective_url}
            discovery_plan = None
            if self.model_compiler:
                feedback = None
                for _attempt in range(2):
                    discovery_plan = await self.model_compiler.discover(
                        rule_collector,
                        effective_url,
                        list_html,
                        feedback,
                        ai_run_id=ai_run_id,
                        attempt_id=attempt_id,
                    )
                    if requires_browser:
                        discovery_plan["transport"] = "browser"
                    if discovery_plan["mode"] != "list_detail":
                        break
                    discovered_records, _next_url = discover_records_from_spec(list_html, effective_url, discovery_plan["list"])
                    if len(discovered_records) >= 2:
                        break
                    feedback = (
                        f"The proposed itemsSelector and detailUrl rule produced only {len(discovered_records)} record(s). "
                        "Choose the repeated record container and a relative detail link selector; body/html is invalid."
                    )
                if discovery_plan["mode"] == "list_detail" and len(discovered_records) < 2:
                    raise ModelCompileError("LLM 列表发现规则经过两次样本验证仍未定位到至少 2 条详情记录。")
            if discovery_plan:
                (artifact_dir / "discovery-plan.json").write_text(
                    json.dumps(discovery_plan, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if discovery_plan and discovery_plan["mode"] == "list_detail":
                detail_urls = [record["detailUrl"] for record in discovered_records]
            elif discovery_plan:
                detail_urls = []
            source_host = urlsplit(collector["sourceUrl"]).hostname
            detail_urls = [url for url in detail_urls if urlsplit(url).hostname == source_host][:4]
            metrics["detailUrlsDiscovered"] = len(detail_urls)
            await progress("discovering_details", 40, metrics)

            samples: list[tuple[str, str]] = []
            for index, detail_url in enumerate(detail_urls[:3], start=1):
                result = await crawler.arun(url=detail_url, config=config)
                if not result.success:
                    continue
                samples.append((detail_url, result.html))
                (artifact_dir / f"detail-{index:03d}.html").write_text(result.html, encoding="utf-8")
            metrics["detailPagesFetched"] = len(samples)
            await progress("fetching_details", 70, metrics)

        rule_collector = {**collector, "sourceUrl": effective_url}
        if self.model_compiler and discovery_plan:
            compiled = await self.model_compiler.compile(
                rule_collector,
                effective_url,
                list_html,
                samples,
                discovery_plan,
                ai_run_id=ai_run_id,
                attempt_id=attempt_id,
            )
            self.contracts.validate_rule_plan(compiled.plan)
            if compiled.plan["mode"] == "list_detail" and compiled.plan["list"]["pagination"]["type"] == "next_link":
                _compiled_records, compiled_next_url = discover_records_from_spec(list_html, effective_url, compiled.plan["list"])
                if not compiled_next_url:
                    raise ModelCompileError("LLM 编译的下一页 selector 未能在列表样本中定位到有效链接。")
            (artifact_dir / "rule-plan.json").write_text(
                json.dumps(compiled.plan, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            candidate = build_candidate_from_plan(rule_collector, self.contracts, compiled.plan, list_html, samples)
            candidate["gatherSpec"]["compiler"]["agent"] = compiled.agent
            candidate["gatherSpec"]["integrity"]["ruleDigest"] = calculate_rule_digest(candidate["gatherSpec"])
            candidate["digest"] = sha256_digest(candidate["gatherSpec"])
            self.contracts.validate_gather_spec(candidate["gatherSpec"])
        else:
            candidate = build_candidate(rule_collector, self.contracts, list_html, samples)
        metrics["warningCount"] = candidate["warningChecks"]
        preview_run = {"id": f"preview_{operation_id}", "ruleVersion": "candidate"}
        preview_samples = samples if candidate["mode"] == "list_detail" else [(collector["sourceUrl"], list_html)]
        preview_records: dict[str, dict[str, str]] = {}
        if candidate["mode"] == "list_detail":
            records, _next_url = discover_records_from_spec(
                list_html,
                effective_url,
                candidate["gatherSpec"]["collect"]["list"],
            )
            preview_records = {record["detailUrl"]: record for record in records if record.get("detailUrl")}
        preview_items = [
            make_item(
                {**collector, "candidate": candidate},
                preview_run,
                url,
                html,
                index,
                source_record=preview_records.get(url),
            )
            for index, (url, html) in enumerate(preview_samples, 1)
        ]
        if not any(item["decision"] == "accepted" for item in preview_items):
            reason = preview_items[0].get("rejectionReason") if preview_items else "规则没有产生任何样本 Item"
            raise ModelCompileError(f"LLM 规则未通过确定性样本验证：{reason}")
        await progress("validating", 90, metrics)
        return ExplorationResult(candidate=candidate, preview_items=preview_items, metrics=metrics)
