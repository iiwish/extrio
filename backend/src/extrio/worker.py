import asyncio
import copy
import logging
import signal
from datetime import UTC, datetime
from typing import Any

from extrio.collector_lifecycle import LifecycleError, require_active
from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.delivery import OUTCOME_DELIVERED, WebhookDispatcher
from extrio.explorer import Crawl4AIExplorer
from extrio.instance_guard import instance_lock
from extrio.integrity import IntegrityError, canonical_bytes, verify_rule_attestation
from extrio.job_control import JobCancelled, JobLeaseLost, JobTimedOut, finish_resources, owned_transaction, renew_job
from extrio.model_budget import BudgetError
from extrio.model_gateway import CompilationContextError, ModelRepairNotApplicableError, ModelRuleCompiler
from extrio.runtime import CrawleeRuntime
from extrio.runtime_health import HEARTBEAT_SECONDS, WorkerHeartbeat, deployment_digest
from extrio.source_network import SourceNetworkError
from extrio.store import DEFAULT_COLLECTOR_SCHEDULE, Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("extrio.worker")
NORMAL_STOP_REASONS = {"not_applicable", "next_link_exhausted", "time_window_reached", "checkpoint_reached", "max_pages"}
REVISION_FIELDS = ("title", "publishedAt", "content", "buyer", "budget", "region")
DELIVERY_BATCH_LIMIT = 1
DELIVERABLE_CHANGE_TYPES = frozenset({"new", "updated"})
CONSECUTIVE_FAILURE_PAUSE_THRESHOLD = 3


def _revision_values(item: dict[str, Any], fingerprint_fields: list[str] | None = None) -> dict[str, Any]:
    extracted = item.get("extractedData")
    if isinstance(extracted, dict) and extracted:
        if fingerprint_fields:
            return {field: extracted.get(field) for field in fingerprint_fields}
        return extracted
    return {field: item.get(field) for field in REVISION_FIELDS}


def _change_value(value: Any) -> str:
    return value if isinstance(value, str) else canonical_bytes(value).decode("utf-8")


def classify_items(
    items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
    collector_id: str,
    fingerprint_fields: list[str] | None = None,
) -> dict[str, int]:
    latest_by_entity: dict[str, dict[str, Any]] = {}
    for previous in previous_items:
        if (
            previous.get("collectorId") == collector_id
            and previous.get("decision") == "accepted"
            and previous.get("entityKey") not in latest_by_entity
        ):
            latest_by_entity[previous["entityKey"]] = previous

    metrics = {"newItems": 0, "updatedItems": 0, "unchangedItems": 0}
    for item in items:
        if item.get("decision") != "accepted":
            item["changeType"] = None
            continue
        previous = latest_by_entity.get(item["entityKey"])
        if previous is None:
            item["changeType"] = "new"
            item["revision"] = 1
            metrics["newItems"] += 1
            continue

        previous_values = _revision_values(previous, fingerprint_fields)
        current_values = _revision_values(item, fingerprint_fields)
        changes = [
            {"field": field, "before": _change_value(previous_values.get(field)), "after": _change_value(current_values.get(field))}
            for field in sorted({*previous_values, *current_values})
            if canonical_bytes(previous_values.get(field)) != canonical_bytes(current_values.get(field))
        ]
        item["changeSummary"] = changes
        item["observationHistory"] = [*previous.get("observationHistory", []), *item.get("observationHistory", [])][-50:]
        if changes:
            item["changeType"] = "updated"
            item["revision"] = int(previous.get("revision") or 0) + 1
            metrics["updatedItems"] += 1
        else:
            item["changeType"] = "unchanged"
            item["revision"] = int(previous.get("revision") or 1)
            metrics["unchangedItems"] += 1
    return metrics


def final_run_status(*, accepted: int, rejected: int, stop_reason: str) -> str:
    if stop_reason not in NORMAL_STOP_REASONS:
        return "partially_succeeded" if accepted else "failed"
    if rejected:
        return "partially_succeeded" if accepted else "failed"
    return "succeeded"


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.store = Store(self.settings.database_path)
        self.contracts = ContractBundle(self.settings.contracts_path)
        self.cipher = CredentialCipher(self.settings.credential_encryption_key_path)
        compiler = ModelRuleCompiler(self.store, self.cipher)
        self.model_compiler = compiler
        self.explorer = Crawl4AIExplorer(
            self.contracts, self.settings.artifact_path, compiler, allow_http=self.store.effective_allow_http_public
        )
        self.runtime = CrawleeRuntime(self.settings.artifact_path, allow_http=self.store.effective_allow_http_public)
        self.dispatcher = WebhookDispatcher(self.store, self.cipher)
        self.stop_event = asyncio.Event()
        self.heartbeat = WorkerHeartbeat(self.store, deployment_digest(self.settings))

    async def _progress(
        self,
        operation_id: str,
        phase: str,
        progress: int,
        metrics: dict[str, int],
        ai_run_id: str | None = None,
        connection=None,
    ) -> None:
        if ai_run_id:
            self.store.update_ai_activity(
                operation_id,
                ai_run_id,
                status="running",
                phase=phase,
                progress=progress,
                metrics=metrics,
                error=None,
                connection=connection,
            )
            return
        self.store.update_operation(
            operation_id, status="running", phase=phase, progress=progress, metrics=metrics, error=None, connection=connection
        )

    def _complete_ai_run(self, ai_run_id: str, connection=None, **changes: Any) -> dict[str, Any]:
        ai_run = self.store.get_ai_run(ai_run_id, connection)
        if ai_run is None:
            raise RuntimeError(f"AI run {ai_run_id} not found")
        finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        started_at = ai_run.get("startedAt") or ai_run["createdAt"]
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        return self.store.update_ai_run(
            ai_run_id,
            connection=connection,
            finishedAt=finished_at,
            durationMs=max(0, int((finished - started).total_seconds() * 1000)),
            **changes,
        )

    async def process(self, job: dict[str, Any]) -> None:
        if job["kind"] == "field_suggestion":
            await self._process_owned(job)
            return
        renew_job(self.store, job)
        task = asyncio.create_task(self._process_owned(job))
        interval = min(0.5, job["leaseSeconds"] / 3)
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=interval)
                if task.done():
                    break
                if getattr(self, "stop_event", None) and self.stop_event.is_set():
                    raise JobLeaseLost("worker stopped; leave lease for recovery")
                renew_job(self.store, job)
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _process_owned(self, job: dict[str, Any]) -> None:
        if job["kind"] == "field_suggestion":
            from extrio.field_suggestions import finish_suggestion

            fields = await asyncio.wait_for(
                self.model_compiler.suggest_fields(job["payload"]["snapshot"], job["id"], job["payload"]["attempt"]), timeout=95
            )
            finish_suggestion(self.store, job, fields=fields)
            return
        operation_id = job["operationId"]
        collector_id = job["payload"]["collectorId"]
        collector = self.store.get_collector(collector_id)
        if collector is None:
            raise RuntimeError(f"Collector {collector_id} not found")
        require_active(collector)
        if job["payload"].get("managementRevision", 0) != collector.get("managementRevision", 0):
            raise LifecycleError("COLLECTOR_CONFLICT")

        ai_run_id = job["payload"].get("aiRunId")

        async def progress(phase: str, value: int, metrics: dict[str, int]) -> None:
            with owned_transaction(self.store, job) as connection:
                await self._progress(operation_id, phase, value, metrics, ai_run_id, connection)

        if job["kind"] == "explore":
            if not ai_run_id:
                raise RuntimeError("exploration job is missing its AI run")
            compilation_context = self.store.collector_compilation_context(collector)
            # Repairs reuse the exploration pipeline end to end; the old
            # GatherSpec is read at processing time so the frozen contract
            # always comes from the collector's current published/candidate rule.
            repair_spec = None
            if job["payload"].get("repair"):
                repair_spec = (collector.get("candidate") or {}).get("gatherSpec")
                if not isinstance(repair_spec, dict) or not repair_spec:
                    raise ModelRepairNotApplicableError("Collector 没有可修复的已发布规则或候选规则。")
            attempt = self.store.start_ai_attempt(ai_run_id)
            job["payload"]["aiAttemptId"] = attempt["id"]

            async def diagnostic(summary):
                with owned_transaction(self.store, job) as connection:
                    self.store.update_ai_run(ai_run_id, connection, evidence=summary)

            evidence_options = (
                {"diagnostic": diagnostic, "prior_evidence": self.store.get_ai_run(ai_run_id).get("evidence")}
                if isinstance(self.explorer, Crawl4AIExplorer)
                else {}
            )
            result = await asyncio.wait_for(
                self.explorer.explore(
                    compilation_context,
                    operation_id,
                    progress,
                    ai_run_id,
                    attempt["id"],
                    repair_spec=repair_spec,
                    guidance=job["payload"].get("guidance"),
                    **evidence_options,
                ),
                timeout=300,
            )
            collector.update(
                status="ready_review",
                activeOperationId=None,
                candidate=result.candidate,
                previewItems=result.preview_items,
                reviewDecisions=None,
                updatedAt="刚刚",
            )
            if collector.get("collectionMigration"):
                collector["collectionMigration"] = {**collector["collectionMigration"], "status": "ready_review"}
            accepted_samples = sum(item.get("decision") == "accepted" for item in result.preview_items)
            rejected_samples = sum(item.get("decision") == "rejected" for item in result.preview_items)
            with owned_transaction(self.store, job) as connection:
                from extrio.collection_workflows import lock_collector

                lock_collector(self.store, connection, collector_id)
                current = self.store.get_collector(collector_id, connection)
                fields = ("status", "activeOperationId", "candidate", "previewItems", "reviewDecisions", "updatedAt")
                current.update({key: collector[key] for key in fields})
                if collector.get("collectionMigration"):
                    current["collectionMigration"] = collector["collectionMigration"]
                self.store.save_collector(current, connection)
                self.store.update_ai_activity(
                    operation_id,
                    ai_run_id,
                    status="succeeded",
                    phase="completed",
                    progress=100,
                    metrics=result.metrics,
                    error=None,
                    connection=connection,
                )
                self.store.finish_ai_attempt(attempt["id"], status="succeeded", error=None, connection=connection)
                self._complete_ai_run(
                    ai_run_id,
                    connection=connection,
                    status="succeeded",
                    phase="completed",
                    progress=100,
                    resultStatus="candidate_ready",
                    reviewStatus="ready_review",
                    candidateRuleDigest=result.candidate.get("digest"),
                    validationSummary={
                        "acceptedSamples": accepted_samples,
                        "rejectedSamples": rejected_samples,
                        "warningCount": int(result.metrics.get("warningCount", 0)),
                    },
                    error=None,
                )
                self.store.finish_job(job["id"], connection)
            return

        if job["kind"] == "run":
            run_id = job["payload"]["runId"]
            run = self.store.get_run(run_id)
            if run is None:
                raise RuntimeError(f"Run {run_id} not found")
            integrity = job["payload"].get("integrity")
            if not integrity:
                raise IntegrityError("run job is missing its fixed integrity context")
            rule_version = self.store.get_rule_version(integrity["ruleVersionId"])
            attestation = self.store.get_rule_attestation(integrity["attestationId"])
            signing_key = self.store.get_signing_key(integrity["keyId"])
            if not rule_version or not attestation or not signing_key:
                raise IntegrityError("run integrity references cannot be resolved")
            verified = verify_rule_attestation(
                spec=rule_version["gatherSpec"],
                attestation=attestation,
                signing_key=signing_key,
                contracts=self.contracts,
                expected_rule_version_id=integrity["ruleVersionId"],
                expected_tenant_id=rule_version["tenantId"],
            )
            if any(verified[key] != integrity[key] for key in ("attestationId", "ruleDigest", "keyId", "trustRevision")):
                raise IntegrityError("run integrity context changed after command acceptance")
            policy = self.store.get_collection_policy(job["payload"].get("policyVersionId", ""))
            if not policy or policy.get("digest") != job["payload"].get("policyDigest"):
                raise IntegrityError("run collection policy context changed after command acceptance")
            collector = copy.deepcopy(collector)
            collector["candidate"]["gatherSpec"] = rule_version["gatherSpec"]
            collector["collectionPolicy"] = policy
            run.update(
                status="running",
                summary="Crawlee 正在执行固定版本规则。",
                localEvidenceRef=f"attempt_{job['attempts']}",
                localEvidenceDigest=None,
            )
            with owned_transaction(self.store, job) as connection:
                self.store.save_run(run, connection)
            budget = rule_version["gatherSpec"]["collect"]["budget"]
            try:
                result = await asyncio.wait_for(self.runtime.run(collector, run, progress), timeout=budget.get("maxDurationSeconds", 300))
            except TimeoutError as exc:
                raise JobTimedOut("run duration budget exhausted") from exc
            fingerprint_fields = collector["candidate"]["gatherSpec"]["contract"]["fingerprintFields"]
            result.metrics.update(
                classify_items(
                    result.items,
                    self.store.latest_accepted_items(collector_id, {item["entityKey"] for item in result.items}),
                    collector_id,
                    fingerprint_fields,
                )
            )
            accepted = sum(item["decision"] == "accepted" for item in result.items)
            rejected = len(result.items) - accepted
            final_status = final_run_status(accepted=accepted, rejected=rejected, stop_reason=result.pagination_stop_reason)
            checkpoint_after = None
            if final_status == "succeeded" and result.pagination_stop_reason != "max_pages" and result.watermark_candidate:
                previous_watermark = (run.get("checkpointBefore") or {}).get("watermark")
                watermark = max(filter(None, [previous_watermark, result.watermark_candidate]))
                checkpoint_after = {
                    "collectorId": collector_id,
                    "policyVersionId": policy["id"],
                    "lastSuccessfulRunId": run_id,
                    "watermark": watermark,
                    "advancedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            run.update(
                status=final_status,
                acceptedCount=accepted,
                rejectedCount=rejected,
                pagesFetched=result.metrics["listPagesFetched"] + result.metrics["detailPagesFetched"],
                listPagesFetched=result.metrics["listPagesFetched"],
                detailUrlsDiscovered=result.metrics["detailUrlsDiscovered"],
                detailPagesFetched=result.metrics["detailPagesFetched"],
                recordsOutsideWindow=result.metrics["recordsOutsideWindow"],
                duplicateDetailUrls=result.metrics["duplicateDetailUrls"],
                newItems=result.metrics["newItems"],
                updatedItems=result.metrics["updatedItems"],
                unchangedItems=result.metrics["unchangedItems"],
                paginationStopReason=result.pagination_stop_reason,
                checkpointAfter=checkpoint_after,
                duration=result.duration,
                localEvidenceDigest=result.evidence_digest,
                artifactMode=result.artifact_mode,
                items=result.items,
                summary=(
                    f"{accepted} 个 accepted Item 已冻结；新增 {result.metrics['newItems']}、更新 {result.metrics['updatedItems']}、"
                    f"未变化 {result.metrics['unchangedItems']}；{rejected} 个候选被拒绝"
                    + (
                        f"；{result.metrics['detailUrlsDiscovered'] - result.metrics['detailPagesFetched']} 个详情页未成功抓取"
                        if result.pagination_stop_reason == "detail_fetch_incomplete"
                        else ""
                    )
                    + "。"
                ),
                recoveryAction=(
                    "部分详情页抓取失败；检查站点访问限制或网络状态后重试。"
                    if result.pagination_stop_reason == "detail_fetch_incomplete"
                    else "运行因预算或异常停止，检查范围与分页上限后重试。"
                    if result.pagination_stop_reason not in NORMAL_STOP_REASONS
                    else ("检查拒绝候选的必填字段；如来源结构漂移，重新探索并发布规则。" if rejected else "无需操作。")
                ),
            )
            collector.update(latestRunId=run_id, previewItems=result.items, activeOperationId=None, updatedAt="刚刚")
            with owned_transaction(self.store, job) as connection:
                from extrio.collection_workflows import lock_collector

                lock_collector(self.store, connection, collector_id)
                self.store.save_run(run, connection)
                self.store.save_items(run_id, result.items, connection)
                current = self.store.get_collector(collector_id, connection)
                current.update({key: collector[key] for key in ("latestRunId", "previewItems", "activeOperationId", "updatedAt")})
                self.store.save_collector(current, connection)
                if checkpoint_after:
                    self.store.save_checkpoint(checkpoint_after, connection)
                operation = self.store.get_operation(operation_id, connection)
                if operation is None:
                    raise RuntimeError(f"Operation {operation_id} not found")
                operation.update(status="succeeded", phase="completed", progress=100, metrics=result.metrics, error=None)
                self.store.save_operation(operation, collector_id, connection)
                enqueued = self.enqueue_run_deliveries(collector_id, result.items, connection)
                self.store.finish_job(job["id"], connection)
            if enqueued:
                logger.info("Enqueued %s webhook deliveries run=%s collector=%s", enqueued, run_id, collector_id)
            if final_status == "failed":
                self.maybe_pause_schedule_after_failures(collector_id)
            return
        raise RuntimeError(f"Unknown job kind: {job['kind']}")

    def maybe_pause_schedule_after_failures(self, collector_id: str) -> bool:
        """Disable the collector schedule after consecutive failed runs (AC-010.2).

        Called right after a run finalizes as ``failed``. The failure window is
        inherently query-based: ``recent_run_statuses`` reads the newest runs
        including the one that just finalized, so a successful run anywhere in
        the window resets the streak without extra bookkeeping. Pausing reuses
        the standard schedule update path (preserving cron and other fields)
        and is a no-op when the schedule is already disabled.
        """

        from extrio.collection_workflows import lock_collector

        with self.store.transaction() as connection:
            lock_collector(self.store, connection, collector_id)
            statuses = self.store.recent_run_statuses(collector_id, CONSECUTIVE_FAILURE_PAUSE_THRESHOLD, connection)
            if len(statuses) < CONSECUTIVE_FAILURE_PAUSE_THRESHOLD or any(status != "failed" for status in statuses):
                return False
            collector = self.store.get_collector(collector_id, connection)
            schedule = (collector or {}).get("schedule") or {}
            if not schedule.get("enabled"):
                return False
            values = {key: schedule[key] for key in DEFAULT_COLLECTOR_SCHEDULE}
            values["enabled"] = False
            updated = self.store.save_schedule(collector_id, values, connection)
            self.store._append_audit_event(
                connection,
                tenant_id=get_settings().tenant_id,
                target_type="collector",
                target_id=collector_id,
                audit={
                    "actorId": "system",
                    "action": "schedule.auto_paused",
                    "requestId": f"failure_pause_{collector_id}",
                    "details": {"consecutiveFailures": CONSECUTIVE_FAILURE_PAUSE_THRESHOLD},
                },
                before_digest=None,
                after_digest=None,
            )
        logger.info(
            "schedule auto-paused after %d consecutive failures collector=%s schedule=%s",
            CONSECUTIVE_FAILURE_PAUSE_THRESHOLD,
            collector_id,
            updated["schedule"]["id"],
        )
        return True

    def enqueue_run_deliveries(self, collector_id: str, items: list[dict[str, Any]], connection=None) -> int:
        """Enqueue one webhook delivery per accepted new/updated item and enabled sink.

        Rejected and unchanged items never produce deliveries; with no enabled
        sinks this is a no-op. Idempotency is enforced by the store per
        ``(item_event_id, sink_id)``.
        """

        sinks = [sink for sink in self.store.list_sinks_for_collector(collector_id, connection) if sink["enabled"]]
        if not sinks:
            return 0
        enqueued = 0
        for item in items:
            if item.get("decision") != "accepted" or item.get("changeType") not in DELIVERABLE_CHANGE_TYPES:
                continue
            for sink in sinks:
                try:
                    self.store.enqueue_delivery(
                        collector_id=collector_id, sink_id=sink["id"], item_event_id=str(item["id"]), connection=connection
                    )
                    enqueued += 1
                except KeyError:
                    logger.warning("Skipped delivery enqueue for removed sink=%s item=%s", sink["id"], item["id"])
        return enqueued

    async def process_due_deliveries(self) -> int:
        """Claim due deliveries and deliver them; returns how many were processed."""

        claimed = self.store.claim_due_deliveries(DELIVERY_BATCH_LIMIT, lease_seconds=self.settings.worker_lease_seconds)
        if not claimed:
            return 0
        outcomes = await asyncio.to_thread(self.dispatcher.process_batch, claimed)
        logger.info("Delivery cycle claimed=%s delivered=%s", len(claimed), outcomes.count(OUTCOME_DELIVERED))
        return len(claimed)

    def fail(self, job: dict[str, Any], exc: Exception) -> None:
        if job["kind"] == "field_suggestion":
            from extrio.field_suggestions import finish_suggestion

            finish_suggestion(
                self.store, job, error={"code": "FIELD_SUGGESTION_FAILED", "message": "字段建议生成失败，请检查默认模型配置并重新生成"}
            )
            return
        operation_id = job["operationId"]
        error = {
            "code": getattr(exc, "code", "INTERNAL_ERROR"),
            "message": "任务执行失败，请根据错误代码检查实例状态和配置",
            "requestId": f"worker_{operation_id}",
            "retryable": bool(getattr(exc, "retryable", False)),
            "pointer": None,
            "details": {"jobKind": job["kind"]},
        }
        if isinstance(exc, SourceNetworkError):
            error["message"] = "来源网络、授权边界或结构校验失败"
            reason = str(exc)
            if reason == "browser_navigation_timed_out":
                error["message"] = "来源页面加载超时，自动重试后仍未完成。请稍后重试当前任务。"
                error["retryable"] = True
            elif reason == "source_request_timed_out":
                error["message"] = "来源请求超时，请稍后重试。"
                error["retryable"] = True
            elif reason == "browser_fetch_failed":
                error["message"] = "来源浏览器加载失败，请查看任务详情并稍后重试。"
            if reason.replace("_", "").isalnum() and len(reason) <= 80:
                error["details"]["reason"] = reason
        elif isinstance(exc, CompilationContextError):
            error["message"] = "已验证的列表交接上下文无效，已停止调用模型。请重新探索来源；持续失败时检查编译器。"
        elif isinstance(exc, IntegrityError):
            error["message"] = "规则签名或受信任密钥校验失败，请重新审核规则与密钥状态"
        elif isinstance(exc, BudgetError):
            error["message"] = {
                "MODEL_CONTEXT_INSUFFICIENT": "模型输入空间不足以容纳字段合同和必要证据，请检查模型上下文配置",
                "MODEL_OUTPUT_BUDGET_EXCEEDED": "模型输出预算不足，无法生成完整规则，请检查模型输出配置",
                "MODEL_CALL_BUDGET_EXCEEDED": "已达到本次 AI 任务调用上限，证据或字段验证仍未完成",
                "MODEL_DISCOVERY_BUDGET_EXCEEDED": "规则发现阶段额度已用尽，未占用后续编译预留额度；请补充来源说明后重试",
                "MODEL_NO_PROGRESS": "重复调用或验证纠错持续无进展，已停止尝试；请检查来源说明和验证反馈",
                "MODEL_TOKEN_BUDGET_EXCEEDED": "已达到本次 AI 任务 token 预算，证据或字段验证仍未完成",
                "MODEL_TIME_BUDGET_EXCEEDED": "已达到本次 AI 任务时间上限，未提交未验证的候选",
            }.get(exc.code, "AI 任务预算不足，未提交未验证的候选")
        if isinstance(exc, JobLeaseLost):
            return
        try:
            with owned_transaction(self.store, job, allow_cancel=True) as connection:
                cancelled = self.store.get_operation(operation_id, connection).get("cancelRequested") or isinstance(exc, JobCancelled)
                status = "cancelled" if cancelled else "timed_out" if isinstance(exc, (JobTimedOut, TimeoutError)) else "failed"
                if cancelled:
                    error.update(code="JOB_CANCELLED", message="Job cancelled")
                elif status == "timed_out":
                    error.update(code="JOB_TIMED_OUT", message="Job duration budget exhausted")
                finish_resources(self.store, connection, job, error, status=status)
                if isinstance(exc, IntegrityError) and job["payload"].get("runId"):
                    run = self.store.get_run(job["payload"]["runId"], connection)
                    run["integrityStatus"] = "invalid"
                    self.store.save_run(run, connection)
        except JobLeaseLost:
            logger.info("Ignoring stale failure operation=%s", operation_id)
            return
        if status == "failed" and job["payload"].get("runId"):
            self.maybe_pause_schedule_after_failures(job["payload"]["collectorId"])

    async def serve(self) -> None:
        with instance_lock(self.settings.artifact_path):
            await self._serve_active()

    async def _serve_active(self) -> None:
        self.store.initialize()
        self.heartbeat.pulse()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        retention_task = asyncio.create_task(self._retention_loop())
        try:
            await self._serve_jobs()
        finally:
            heartbeat_task.cancel()
            retention_task.cancel()
            await asyncio.gather(heartbeat_task, retention_task, return_exceptions=True)
            self.heartbeat.stop()

    async def _retention_loop(self) -> None:
        from extrio.local_evidence import prune_expired_evidence

        while not self.stop_event.is_set():
            try:
                work = asyncio.create_task(asyncio.to_thread(prune_expired_evidence, self.settings.artifact_path))
                try:
                    result = await asyncio.shield(work)
                except asyncio.CancelledError:
                    await work
                    raise
                if result["invalidManifests"]:
                    logger.warning("Retention skipped %s invalid evidence manifests", result["invalidManifests"])
            except OSError:
                logger.error("Evidence retention failed")
            await asyncio.sleep(3600)

    async def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                self.heartbeat.pulse()
            except Exception:
                logger.error("Worker heartbeat persistence failed")
                self.stop_event.set()

    async def _serve_jobs(self) -> None:
        logger.info("Worker started; database=%s", self.settings.database_path)
        while not self.stop_event.is_set():
            job = self.store.claim_job(self.settings.worker_lease_seconds)
            if job is None:
                from extrio.field_suggestions import claim_suggestion

                job = claim_suggestion(self.store)
            if job is None:
                processed = await self.process_due_deliveries()
                if processed == 0:
                    try:
                        await asyncio.wait_for(self.stop_event.wait(), timeout=self.settings.worker_poll_seconds)
                    except TimeoutError:
                        pass
                continue
            logger.info("Processing %s operation=%s", job["kind"], job["operationId"])
            try:
                await self.process(job)
            except Exception as exc:  # noqa: BLE001
                logger.error("Job failed operation=%s type=%s", job["operationId"], type(exc).__name__)
                self.fail(job, exc)
            await self.process_due_deliveries()


async def _main() -> None:
    worker = Worker()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            loop.add_signal_handler(getattr(signal, name), worker.stop_event.set)
    await worker.serve()


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()
