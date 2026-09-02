import asyncio
import copy
import logging
import signal
from datetime import UTC, datetime
from typing import Any

from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.explorer import Crawl4AIExplorer
from extrio.integrity import IntegrityError, verify_rule_attestation
from extrio.model_gateway import ModelRuleCompiler
from extrio.runtime import CrawleeRuntime
from extrio.store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("extrio.worker")
NORMAL_STOP_REASONS = {"not_applicable", "next_link_exhausted", "time_window_reached", "checkpoint_reached"}
REVISION_FIELDS = ("title", "publishedAt", "content", "buyer", "budget", "region")


def _revision_values(item: dict[str, Any], fingerprint_fields: list[str] | None = None) -> dict[str, Any]:
    extracted = item.get("extractedData")
    if isinstance(extracted, dict) and extracted:
        if fingerprint_fields:
            return {field: extracted.get(field) for field in fingerprint_fields}
        return extracted
    return {field: item.get(field) for field in REVISION_FIELDS}


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
            {"field": field, "before": str(previous_values.get(field) or ""), "after": str(current_values.get(field) or "")}
            for field in sorted({*previous_values, *current_values})
            if (previous_values.get(field) or "") != (current_values.get(field) or "")
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
        compiler = ModelRuleCompiler(self.store, CredentialCipher(self.settings.credential_encryption_key_path))
        self.explorer = Crawl4AIExplorer(self.contracts, self.settings.artifact_path, compiler)
        self.runtime = CrawleeRuntime(self.settings.artifact_path)
        self.stop_event = asyncio.Event()

    async def _progress(
        self,
        operation_id: str,
        phase: str,
        progress: int,
        metrics: dict[str, int],
        ai_run_id: str | None = None,
    ) -> None:
        self.store.update_operation(operation_id, status="running", phase=phase, progress=progress, metrics=metrics, error=None)
        if ai_run_id:
            self.store.update_ai_run(ai_run_id, status="running", phase=phase, progress=progress, error=None)

    def _complete_ai_run(self, ai_run_id: str, **changes: Any) -> dict[str, Any]:
        ai_run = self.store.get_ai_run(ai_run_id)
        if ai_run is None:
            raise RuntimeError(f"AI run {ai_run_id} not found")
        finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        started_at = ai_run.get("startedAt") or ai_run["createdAt"]
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        return self.store.update_ai_run(
            ai_run_id,
            finishedAt=finished_at,
            durationMs=max(0, int((finished - started).total_seconds() * 1000)),
            **changes,
        )

    async def process(self, job: dict[str, Any]) -> None:
        operation_id = job["operationId"]
        collector_id = job["payload"]["collectorId"]
        collector = self.store.get_collector(collector_id)
        if collector is None:
            raise RuntimeError(f"Collector {collector_id} not found")

        ai_run_id = job["payload"].get("aiRunId")

        async def progress(phase: str, value: int, metrics: dict[str, int]) -> None:
            await self._progress(operation_id, phase, value, metrics, ai_run_id)

        if job["kind"] == "explore":
            if not ai_run_id:
                raise RuntimeError("exploration job is missing its AI run")
            attempt = self.store.start_ai_attempt(ai_run_id)
            job["payload"]["aiAttemptId"] = attempt["id"]
            result = await self.explorer.explore(collector, operation_id, progress, ai_run_id, attempt["id"])
            collector.update(
                status="ready_review",
                activeOperationId=None,
                candidate=result.candidate,
                previewItems=result.preview_items,
                reviewDecisions=None,
                updatedAt="刚刚",
            )
            self.store.save_collector(collector)
            self.store.update_operation(
                operation_id, status="succeeded", phase="completed", progress=100, metrics=result.metrics, error=None
            )
            accepted_samples = sum(item.get("decision") == "accepted" for item in result.preview_items)
            rejected_samples = sum(item.get("decision") == "rejected" for item in result.preview_items)
            self.store.finish_ai_attempt(attempt["id"], status="succeeded", error=None)
            self._complete_ai_run(
                ai_run_id,
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
            run.update(status="running", summary="Crawlee 正在执行固定版本规则。")
            self.store.save_run(run)
            result = await self.runtime.run(collector, run, progress)
            fingerprint_fields = collector["candidate"]["gatherSpec"]["contract"]["fingerprintFields"]
            result.metrics.update(
                classify_items(result.items, self.store.list_items(), collector_id, fingerprint_fields)
            )
            accepted = sum(item["decision"] == "accepted" for item in result.items)
            rejected = len(result.items) - accepted
            final_status = final_run_status(accepted=accepted, rejected=rejected, stop_reason=result.pagination_stop_reason)
            checkpoint_after = None
            if final_status == "succeeded" and result.watermark_candidate:
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
            with self.store.transaction() as connection:
                self.store.save_run(run, connection)
                self.store.save_items(run_id, result.items, connection)
                self.store.save_collector(collector, connection)
                if checkpoint_after:
                    self.store.save_checkpoint(checkpoint_after, connection)
                operation = self.store.get_operation(operation_id, connection)
                if operation is None:
                    raise RuntimeError(f"Operation {operation_id} not found")
                operation.update(status="succeeded", phase="completed", progress=100, metrics=result.metrics, error=None)
                self.store.save_operation(operation, collector_id, connection)
            return
        raise RuntimeError(f"Unknown job kind: {job['kind']}")

    def fail(self, job: dict[str, Any], exc: Exception) -> None:
        operation_id = job["operationId"]
        collector_id = job["payload"].get("collectorId")
        error = {
            "code": getattr(exc, "code", "INTERNAL_ERROR"),
            "message": str(exc)[:500] or type(exc).__name__,
            "requestId": f"worker_{operation_id}",
            "retryable": bool(getattr(exc, "retryable", False)),
            "pointer": None,
            "details": {"jobKind": job["kind"]},
        }
        try:
            self.store.update_operation(operation_id, status="failed", phase="completed", progress=100, error=error)
            ai_run_id = job["payload"].get("aiRunId")
            ai_attempt_id = job["payload"].get("aiAttemptId")
            if ai_attempt_id:
                self.store.finish_ai_attempt(ai_attempt_id, status="failed", error=error)
            if ai_run_id:
                self._complete_ai_run(
                    ai_run_id,
                    status="failed",
                    phase="completed",
                    progress=100,
                    resultStatus="no_candidate",
                    reviewStatus="not_ready",
                    error=error,
                )
            collector = self.store.get_collector(collector_id) if collector_id else None
            if collector:
                collector["activeOperationId"] = None
                if job["kind"] == "explore":
                    collector["status"] = job["payload"].get("previousStatus", "draft")
                self.store.save_collector(collector)
            run_id = job["payload"].get("runId")
            run = self.store.get_run(run_id) if run_id else None
            if run:
                run.update(
                    status="failed",
                    duration="—",
                    summary=f"运行失败：{error['message']}",
                    recoveryAction="检查 Worker 日志后重试。",
                )
                if isinstance(exc, IntegrityError):
                    run["integrityStatus"] = "invalid"
                self.store.save_run(run)
        finally:
            self.store.fail_job(job["id"], str(exc))

    async def serve(self) -> None:
        self.store.initialize()
        logger.info("Worker started; database=%s", self.settings.database_path)
        while not self.stop_event.is_set():
            job = self.store.claim_job(self.settings.worker_lease_seconds)
            if job is None:
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=self.settings.worker_poll_seconds)
                except TimeoutError:
                    pass
                continue
            logger.info("Processing %s operation=%s", job["kind"], job["operationId"])
            try:
                await self.process(job)
                self.store.finish_job(job["id"])
            except Exception as exc:  # noqa: BLE001
                logger.exception("Job failed operation=%s", job["operationId"])
                self.fail(job, exc)


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
