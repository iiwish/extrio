import asyncio
import copy
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from crawl4ai import CacheMode, CrawlerRunConfig
from jsonschema import ValidationError
from soupsieve.util import SelectorSyntaxError

from extrio.adaptive_compile import CURRENT_SESSION
from extrio.config import get_settings
from extrio.contracts import ContractBundle, sha256_digest
from extrio.harvest import (
    build_candidate,
    build_candidate_from_plan,
    contract_field_values,
    discover,
    discover_records_from_spec,
    embedded_list_url,
    looks_like_dynamic_list_shell,
    make_item,
)
from extrio.integrity import calculate_rule_digest
from extrio.model_budget import BudgetError
from extrio.model_gateway import (
    ModelCompileError,
    ModelRepairNotApplicableError,
    ModelRepairValidationError,
    ModelRuleCompiler,
)
from extrio.pagination import pagination_hints
from extrio.source_clients import RestrictedBrowser
from extrio.source_network import SourceNetwork

logger = logging.getLogger("extrio.explorer")

ProgressCallback = Callable[[str, int, dict[str, int]], Awaitable[None]]


def _validation_feedback(exc: Exception, code: str) -> list[dict]:
    if getattr(exc, "issues", None):
        return exc.issues
    if isinstance(exc, ValidationError):
        return [{"code": code, "field": ".".join(map(str, exc.absolute_path)),
                 "reason": exc.message[:500]}]
    return [{"code": code, "reason": str(exc)[:500]}]


def _pagination_issues(plan: dict, html: str, url: str) -> list[dict]:
    if plan['mode'] != 'list_detail':
        return []
    pagination = plan['list']['pagination']
    hints = pagination_hints(html, url)
    code = None
    if pagination['type'] == 'next_link':
        _records, next_url = discover_records_from_spec(html, url, plan['list'])
        if not next_url:
            code = 'PAGINATION_NEXT_LINK_MISSING'
    elif hints and pagination['type'] == 'none':
        code = 'PAGINATION_OMITTED'
    elif pagination['type'] == 'page' and any(urlsplit(hint['targetUrl']).path != urlsplit(url).path for hint in hints):
        code = 'PAGINATION_MODE_MISMATCH'
    if not code:
        return []
    return [{'code': code, 'field': 'list.pagination', 'stage': 'list', 'navigationCandidates': hints,
             'reason': 'Choose a real next-link anchor. Static onclick path navigation is supported; do not disable observed pagination.'}]


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


def _apply_repair_contract(candidate: dict[str, Any], old_gather_spec: dict[str, Any]) -> None:
    """Governance invariant: the repaired rule keeps the old rule's data contract verbatim.

    The LLM only fixes selectors, pagination, and transport. The contract sub-object
    (identityFields, fingerprintFields, normalizedItemSchema, fieldBindings, quality,
    tombstonePolicy) is copied from the old GatherSpec — never taken from the model —
    derived digests are recomputed, and any drift the model proposed is logged.
    """
    spec = candidate["gatherSpec"]
    old_contract = copy.deepcopy(old_gather_spec.get("contract") or {})
    if not old_contract:
        raise ModelRepairNotApplicableError("旧规则缺少输出合同，无法执行修复。")
    proposed = spec.get("contract") or {}
    drift = sorted(key for key in set(proposed) | set(old_contract) if proposed.get(key) != old_contract.get(key))
    if drift:
        logger.warning("repair compilation proposed a different contract; forced the previous contract keys=%s", drift)
    spec["contract"] = old_contract
    old_ref = old_gather_spec.get("collectionVersionRef") or {}
    if old_ref.get("collectionVersionId", "").startswith("colver_"):
        spec["collectionVersionRef"] = copy.deepcopy(old_ref)
    else:
        spec["contract"]["outputContractDigest"] = sha256_digest(spec["contract"].get("normalizedItemSchema") or {})


def _extractable(html: str, source_url: str, key: str, field: dict[str, Any]) -> bool:
    try:
        value = contract_field_values(html, source_url, {key: field}).get(key)
    except Exception:  # noqa: BLE001 - an unevaluable selector means the value cannot be extracted
        return False
    return bool(str(value if value is not None else "").strip())


def _repair_identity_failures(
    gather_spec: dict[str, Any],
    list_html: str,
    effective_url: str,
    detail_samples: list[tuple[str, str]],
) -> list[str]:
    """Return identity fields whose values cannot be extracted from the fresh snapshots."""
    contract = gather_spec.get("contract") or {}
    collect = gather_spec.get("collect") or {}
    list_fields = collect.get("list", {}).get("fields") or {}
    detail_fields = (collect.get("detail") or {}).get("fields") or {}
    list_records: list[dict[str, str]] = []
    if "detail" in collect:
        try:
            list_records, _next_url = discover_records_from_spec(list_html, effective_url, collect["list"])
        except Exception:  # noqa: BLE001 - a stale selector must surface as a field failure, not a crash
            list_records = []
    failures = []
    for field in contract.get("identityFields") or []:
        field = str(field)
        if field in list_fields:
            if "detail" in collect:
                ok = any(str(record.get(field) or "").strip() for record in list_records)
            else:
                ok = _extractable(list_html, effective_url, field, list_fields[field])
        elif field in detail_fields:
            ok = any(_extractable(html, url, field, detail_fields[field]) for url, html in detail_samples)
        else:
            ok = False
        if not ok:
            failures.append(field)
    return failures


def _repair_detail_urls(
    list_html: str,
    effective_url: str,
    old_gather_spec: dict[str, Any],
    fallback_urls: list[str],
) -> list[str]:
    """Locate detail samples for a repair using the old rule's list selectors first."""
    collect = old_gather_spec.get("collect") or {}
    if "detail" not in collect:
        return []
    try:
        records, _next_url = discover_records_from_spec(list_html, effective_url, collect["list"] or {})
    except Exception:  # noqa: BLE001 - a stale selector must not abort the re-exploration
        return fallback_urls
    urls = [str(record["detailUrl"]) for record in records if record.get("detailUrl")]
    return urls or fallback_urls


class Crawl4AIExplorer:
    def __init__(
        self,
        contracts: ContractBundle,
        artifact_path: Path,
        model_compiler: ModelRuleCompiler | None = None,
        *,
        allow_http: Callable[[], bool] | None = None,
    ):
        self.contracts = contracts
        self.artifact_path = artifact_path
        self.model_compiler = model_compiler
        self.allow_http = allow_http or (lambda: get_settings().allow_http_public)

    async def explore(
        self, collector, operation_id, progress, ai_run_id=None, attempt_id=None, *, repair_spec=None, guidance=None,
        diagnostic=None, prior_evidence=None,
    ) -> ExplorationResult:
        if not isinstance(self.model_compiler, ModelRuleCompiler):
            return await self._explore(collector, operation_id, progress, ai_run_id, attempt_id,
                                       repair_spec=repair_spec, guidance=guidance)
        with self.model_compiler.task_session(report=diagnostic, prior=prior_evidence) as session:
            try:
                result = await asyncio.wait_for(
                    self._explore(collector, operation_id, progress, ai_run_id, attempt_id,
                                  repair_spec=repair_spec, guidance=guidance), timeout=session.budget.remaining_seconds())
            except BaseException as exc:
                session.phase = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
                session.budget.stop_reason = ("MODEL_CALL_CANCELLED" if isinstance(exc, asyncio.CancelledError)
                                             else getattr(exc, "code", "MODEL_TIME_BUDGET_EXCEEDED" if isinstance(exc, TimeoutError)
                                                          else "EVIDENCE_VALIDATION_FAILED"))
                try:
                    await session.notify()
                except Exception:
                    pass  # A cancelled/lost lease cannot write diagnostics or commit a candidate.
                if isinstance(exc, TimeoutError):
                    raise BudgetError("MODEL_TIME_BUDGET_EXCEEDED") from exc
                raise
            await session.notify()
            return result

    async def _explore(
        self,
        collector: dict[str, Any],
        operation_id: str,
        progress: ProgressCallback,
        ai_run_id: str | None = None,
        attempt_id: str | None = None,
        *,
        repair_spec: dict[str, Any] | None = None,
        guidance: str | None = None,
    ) -> ExplorationResult:
        artifact_dir = self.artifact_path / operation_id
        session = CURRENT_SESSION.get()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if repair_spec is not None and self.model_compiler is None:
            raise ModelCompileError("修复编译需要已配置的默认模型，请先在设置中配置供应商与默认模型。")
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
            check_robots_txt=False,
            page_timeout=30_000,
            delay_before_return_html=3.0,
        )
        network = SourceNetwork(
            {urlsplit(collector["sourceUrl"]).hostname or ""},
            allow_localhost=get_settings().allow_http_localhost,
            allow_http=self.allow_http(),
        )
        async with RestrictedBrowser(network) as crawler:
            await progress("fetching_list", 10, metrics)
            list_result = await crawler.arun(url=collector["sourceUrl"], config=config)
            source_html = list_result.html
            requires_browser = looks_like_dynamic_list_shell(source_html)
            if requires_browser:
                settled_result = await crawler.arun(url=collector["sourceUrl"], config=config)
                source_html = settled_result.html
            effective_url = list_result.redirected_url or collector["sourceUrl"]
            list_html = source_html
            detail_urls, _next_url = discover(list_html, effective_url)
            frame_url = embedded_list_url(source_html, collector["sourceUrl"]) if not detail_urls else None
            if frame_url:
                frame_result = await crawler.arun(url=frame_url, config=config)
                (artifact_dir / "source-shell.html").write_text(source_html, encoding="utf-8")
                effective_url = frame_url
                list_html = frame_result.html
                detail_urls, _next_url = discover(list_html, effective_url)
            (artifact_dir / "list-001.html").write_text(list_html, encoding="utf-8")
            metrics["listPagesFetched"] = 1
            rule_collector = {**collector, "sourceUrl": effective_url}
            discovery_plan = None
            if self.model_compiler and repair_spec is None:
                await progress("analyzing_structure", 25, metrics)
                feedback = None
                for discovery_attempt in range(session.budget.max_calls if session else 2):
                    if discovery_attempt:
                        await progress("analyzing_structure", 35, metrics)
                    try:
                        discovery_plan = await self.model_compiler.discover(
                            rule_collector, effective_url, list_html, feedback,
                            guidance=guidance, ai_run_id=ai_run_id, attempt_id=attempt_id,
                        )
                    except (ModelCompileError, ValidationError, SelectorSyntaxError, ValueError) as exc:
                        if not session:
                            raise
                        session.validate_feedback(_validation_feedback(exc, "DISCOVERY_RULE_INVALID"))
                        session.budget.check()
                        continue
                    if requires_browser:
                        discovery_plan["transport"] = "browser"
                    if discovery_plan["mode"] != "list_detail":
                        break
                    try:
                        discovered_records, _next_url = discover_records_from_spec(list_html, effective_url, discovery_plan["list"])
                    except (ValueError, SelectorSyntaxError):
                        if not session:
                            raise
                        discovered_records = []
                    if len(discovered_records) >= 2:
                        issues = _pagination_issues(discovery_plan, list_html, effective_url)
                        if issues:
                            if not session:
                                error = ModelCompileError('列表分页规则未通过样本验证。')
                                error.issues = issues
                                raise error
                            session.validate_feedback(issues)
                            session.budget.check()
                            continue
                        break
                    feedback = (
                        f"The proposed itemsSelector and detailUrl rule produced only {len(discovered_records)} record(s). "
                        "Choose the repeated record container and a relative detail link selector; body/html is invalid."
                    )
                    if session:
                        session.validate_feedback([{"code": "LIST_RECORDS_MISSING", "stage": "list", "field": "detailUrl"}])
                        session.budget.check()
                else:
                    raise ModelCompileError("LLM 列表发现未能在预算内通过样本验证。")
                if discovery_plan is None or (discovery_plan["mode"] == "list_detail" and len(discovered_records) < 2):
                    raise ModelCompileError("LLM 列表发现未能在预算内定位到至少 2 条详情记录。")
            if discovery_plan:
                (artifact_dir / "discovery-plan.json").write_text(
                    json.dumps(discovery_plan, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if discovery_plan and discovery_plan["mode"] == "list_detail":
                detail_urls = [record["detailUrl"] for record in discovered_records]
            elif discovery_plan:
                detail_urls = []
            elif repair_spec is not None:
                detail_urls = _repair_detail_urls(list_html, effective_url, repair_spec, detail_urls)
            source_host = urlsplit(collector["sourceUrl"]).hostname
            detail_urls = list(dict.fromkeys(url for url in detail_urls if urlsplit(url).hostname == source_host))[:4]
            metrics["detailUrlsDiscovered"] = len(detail_urls)

            samples: list[tuple[str, str]] = []
            if detail_urls:
                await progress("discovering_details", 45, metrics)
                await progress("fetching_details", 52, metrics)
                for index, detail_url in enumerate(detail_urls[:3], start=1):
                    result = await crawler.arun(url=detail_url, config=config)
                    samples.append((detail_url, result.html))
                    (artifact_dir / f"detail-{index:03d}.html").write_text(result.html, encoding="utf-8")
            metrics["detailPagesFetched"] = len(samples)

        rule_collector = {**collector, "sourceUrl": effective_url}
        if session:
            session.feedback = []
        while True:
            compiled = None
            try:
                if self.model_compiler and (discovery_plan or repair_spec is not None):
                    await progress("compiling_rule", 70, metrics)
                    method = self.model_compiler.compile_repair_rule_plan if repair_spec is not None else self.model_compiler.compile
                    compiled = await method(rule_collector, effective_url, list_html, samples,
                                            repair_spec if repair_spec is not None else discovery_plan,
                                            guidance=guidance, ai_run_id=ai_run_id, attempt_id=attempt_id)
                    if requires_browser:
                        compiled.plan["transport"] = "browser"
                await progress("validating", 85, metrics)
                result = self._validate_candidate(collector, rule_collector, operation_id, effective_url, list_html,
                                                  samples, compiled, repair_spec, metrics)
                if session:
                    session.budget.check_consumption()
                    issues = _sample_issues(result.candidate, result.preview_items)
                    session.validate_feedback(issues)
                    await session.notify()
                    if issues:
                        session.budget.check()
                        continue
                break
            except (ModelCompileError, ValidationError, SelectorSyntaxError, ValueError) as exc:
                if not session:
                    raise
                code = "TITLE_MISMATCH" if "标题不一致" in str(exc) else "RULE_VALIDATION_FAILED"
                session.validate_feedback(_validation_feedback(exc, code))
                await session.notify()
                session.budget.check()
        if compiled:
            (artifact_dir / "rule-plan.json").write_text(json.dumps(compiled.plan, ensure_ascii=False, indent=2), encoding="utf-8")
        await progress("finalizing", 95, metrics)
        return result

    def _validate_candidate(self, collector, rule_collector, operation_id, effective_url, list_html,
                            samples, compiled, repair_spec, metrics) -> ExplorationResult:
        if compiled is not None:
            self.contracts.validate_rule_plan(compiled.plan)
            issues = _pagination_issues(compiled.plan, list_html, effective_url)
            if issues:
                error = ModelCompileError('候选分页规则未通过样本验证。')
                error.issues = issues
                raise error
            candidate = build_candidate_from_plan(rule_collector, self.contracts, compiled.plan, list_html, samples)
            candidate["gatherSpec"]["compiler"]["agent"] = compiled.agent
            if repair_spec is not None:
                _apply_repair_contract(candidate, repair_spec)
            candidate["gatherSpec"]["integrity"]["ruleDigest"] = calculate_rule_digest(candidate["gatherSpec"])
            candidate["digest"] = sha256_digest(candidate["gatherSpec"])
            self.contracts.validate_gather_spec(candidate["gatherSpec"])
        else:
            candidate = build_candidate(rule_collector, self.contracts, list_html, samples)
        if repair_spec is not None:
            failures = _repair_identity_failures(candidate["gatherSpec"], list_html, effective_url, samples)
            if failures:
                error = ModelRepairValidationError(
                    "修复编译未能从新页面提取身份字段：" + "、".join(failures) + "。请检查站点结构变化后重试。"
                )
                error.issues = [{"code": "IDENTITY_FIELD_MISSING", "field": key} for key in failures]
                raise error
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
            handoff_issues = [{"code": "DETAIL_URL_MISMATCH", "sample": index, "field": "detailUrl", "stage": "list"}
                              for index, (url, _html) in enumerate(preview_samples, 1) if url not in preview_records]
            if handoff_issues:
                error = ModelCompileError("列表交接记录未匹配实际详情样本 URL。")
                error.issues = handoff_issues
                raise error
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
            error = ModelCompileError(f"LLM 规则未通过确定性样本验证：{reason}")
            error.issues = _sample_issues(candidate, preview_items) or [{"code": "SAMPLES_MISSING"}]
            raise error
        return ExplorationResult(candidate=candidate, preview_items=preview_items, metrics=metrics)


def _sample_issues(candidate: dict, items: list[dict]) -> list[dict]:
    issues = []
    seen: dict[str, dict] = {}
    for index, item in enumerate(items, 1):
        if item.get("decision") != "accepted":
            code = "TITLE_MISMATCH" if "标题不一致" in str(item.get("rejectionReason")) else "SAMPLE_REJECTED"
            issue = {"code": code, "sample": index}
            if code == "TITLE_MISMATCH":
                issue.update(field="title", stage="detail", expectedTitle=str(item.get("listTitle", ""))[:240],
                             actualTitle=str(item.get("title", ""))[:240])
            issues.append(issue)
        values = item.get("extractedData") or {}
        for field in candidate["fields"]:
            value = values.get(field["key"])
            if value is None or (isinstance(value, str) and not value.strip()):
                issues.append({"code": "FIELD_MISSING", "field": field["key"], "sample": index,
                               "selector": field["selector"][:300]})
        contract = candidate["gatherSpec"]["contract"]
        # Frozen output excludes internal handoff fields. That handoff is checked against source records above.
        if ("detailUrl" in contract.get("normalizedItemSchema", {}).get("properties", {})
                and contract.get("fieldBindings", {}).get("detailUrl") == "list.detailUrl"):
            if values.get("detailUrl") != item.get("sourceUrl"):
                issues.append({"code": "DETAIL_URL_MISMATCH", "sample": index, "field": "detailUrl"})
        previous = seen.get(item["entityKey"])
        if previous and previous != values:
            issues.append({"code": "IDENTITY_COLLISION", "sample": index})
        seen[item["entityKey"]] = values
    return issues[:32]
