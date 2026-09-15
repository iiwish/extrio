import asyncio
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_collection_versions import client as client
from test_collection_versions import command

import extrio.app as app_module
from extrio.credentials import CredentialCipher
from extrio.harvest import build_candidate
from extrio.runtime import RunResult
from extrio.source_network import SourceNetworkError
from extrio.store import DEFAULT_COLLECTOR_SCHEDULE
from extrio.worker import Worker

LIST_HTML = '<ul class="notice-list"><li><a class="notice-title" href="/detail/a">Notice A</a><time datetime="2026-08-30"></time></li></ul>'
DETAIL_HTML = (
    '<h1 class="notice-title">Notice A</h1><div class="meta"><span data-field="buyer">Buyer</span>'
    '<time datetime="2026-08-30"></time></div><div class="notice-budget"><span class="amount">100</span></div>'
)


def prepared_run(client, *, max_duration=None):
    store = app_module.store
    source = store.create_collector("Recovery", "Collect notices", "https://example.com/list", "example.com")
    source.update(
        status="ready_review",
        candidate=build_candidate(source, app_module.contracts, LIST_HTML, [("https://example.com/detail/a", DETAIL_HTML)]),
    )
    if max_duration is not None:
        from extrio.integrity import calculate_rule_digest

        source["candidate"]["gatherSpec"]["collect"]["budget"]["maxDurationSeconds"] = max_duration
        source["candidate"]["digest"] = calculate_rule_digest(source["candidate"]["gatherSpec"])
    store.save_collector(source)
    result = command(
        client,
        "POST",
        f"/api/v1/collectors/{source['id']}/publish",
        {"reviewDecisions": {"title": "approved", "buyer": "approved", "publishedAt": "approved", "budget": "risk_accepted"}},
        "publish-recovery-source",
    )
    assert result.status_code == 200, result.text
    operation = command(client, "POST", f"/api/v1/collectors/{source['id']}/runs", key="recovery-run-request").json()
    job = store.claim_job(60)
    assert job and job["operationId"] == operation["id"]
    return store, source, operation, job


def result_for(source, run):
    from test_worker import accepted_item

    item = accepted_item(run_id=run["id"])
    item.update(collectorId=source["id"], collectorName=source["name"])
    return RunResult(
        [item],
        {
            "listPagesFetched": 1,
            "detailUrlsDiscovered": 1,
            "detailPagesFetched": 1,
            "recordsOutsideWindow": 0,
            "duplicateDetailUrls": 0,
            "newItems": 0,
            "updatedItems": 0,
            "unchangedItems": 0,
            "warningCount": 0,
        },
        "next_link_exhausted",
        "0.1s",
        "2026-08-30",
    )


def make_worker(store, runtime):
    worker = Worker.__new__(Worker)
    worker.store = store
    worker.contracts = app_module.contracts
    worker.runtime = runtime
    return worker


def test_source_exceptions_pause_after_three_failures_without_checkpoint(client):
    store, source, operation, job = prepared_run(client)
    store.save_schedule(source["id"], {**DEFAULT_COLLECTOR_SCHEDULE, "enabled": True})
    from test_worker import store_run

    for index in range(2):
        store_run(store, f"run_source_failed_{index}", source["id"], "failed")
    worker = make_worker(store, None)
    worker.fail(job, SourceNetworkError("source_structure_mismatch"))
    assert store.get_run(operation["resourceId"])["status"] == "failed"
    assert store.get_collector(source["id"])["schedule"]["enabled"] is False
    assert store.get_checkpoint(source["id"]) is None


def test_unexpected_worker_failure_does_not_expose_secrets_or_local_paths(client):
    store, source, operation, job = prepared_run(client)
    make_worker(store, None).fail(job, OSError("/private/keys/secret.pem token=fixture-secret https://user:password@example.test"))
    error = store.get_operation(operation["id"])["error"]
    assert "fixture-secret" not in str(error)
    assert "/private/" not in str(error)
    assert "password" not in str(error)


def test_browser_timeout_reports_actionable_reason_without_raw_diagnostics(client):
    store, _source, operation, job = prepared_run(client)
    make_worker(store, None).fail(job, SourceNetworkError("browser_navigation_timed_out"))
    error = store.get_operation(operation["id"])["error"]
    assert error["retryable"] is True
    assert error["details"]["reason"] == "browser_navigation_timed_out"
    assert "加载超时" in error["message"]
    assert "http_status_0" not in str(error)


def test_published_attestation_records_the_actual_reviewer(client):
    store, source, operation, job = prepared_run(client)
    run = store.get_run(operation["resourceId"])
    attestation = store.get_rule_attestation(run["ruleAttestationId"])
    assert attestation["approval"]["reviewerSubjectIds"] == ["user_local_development"]


@pytest.mark.asyncio
async def test_expired_worker_cannot_commit_after_reclaim(client):
    store, source, operation, old = prepared_run(client)
    replacement = None

    class Runtime:
        async def run(self, source, run, progress):
            nonlocal replacement
            with store.transaction() as conn:
                conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", old["id"]))
            replacement = store.claim_job(60)
            return result_for(source, run)

    with pytest.raises(RuntimeError, match="lease"):
        await make_worker(store, Runtime()).process(old)
    assert replacement["attempts"] == old["attempts"] + 1
    assert store.get_run(operation["resourceId"])["status"] != "succeeded"
    assert store.list_items() == []
    assert store.get_checkpoint(source["id"]) is None


@pytest.mark.asyncio
async def test_result_preserves_concurrent_collector_settings(client):
    store, source, operation, job = prepared_run(client)

    class Runtime:
        async def run(self, source, run, progress):
            latest = store.get_collector(source["id"])
            latest["name"] = "Operator rename during run"
            store.save_collector(latest)
            return result_for(source, run)

    await make_worker(store, Runtime()).process(job)
    assert store.get_collector(source["id"])["name"] == "Operator rename during run"


@pytest.mark.asyncio
async def test_heartbeat_renews_long_run_and_shutdown_leaves_it_recoverable(client):
    store, source, operation, job = prepared_run(client)
    job["leaseSeconds"] = 1
    started, stopped = asyncio.Event(), asyncio.Event()

    class Runtime:
        async def run(self, source, run, progress):
            started.set()
            try:
                await asyncio.sleep(5)
            finally:
                stopped.set()

    worker = make_worker(store, Runtime())
    worker.stop_event = asyncio.Event()
    task = asyncio.create_task(worker.process(job))
    await started.wait()
    await asyncio.sleep(1.3)
    assert store.claim_job(60) is None
    worker.stop_event.set()
    with pytest.raises(RuntimeError, match="lease") as error:
        await task
    worker.fail(job, error.value)
    assert stopped.is_set()
    assert store.get_operation(operation["id"])["status"] not in {"failed", "succeeded", "cancelled"}


@pytest.mark.asyncio
async def test_duration_budget_stops_runtime_without_advancing_checkpoint(client):
    store, source, operation, job = prepared_run(client, max_duration=1)
    stopped = asyncio.Event()

    class Runtime:
        async def run(self, source, run, progress):
            try:
                await asyncio.sleep(5)
            finally:
                stopped.set()

    worker = make_worker(store, Runtime())
    with pytest.raises(RuntimeError, match="duration") as error:
        await worker.process(job)
    worker.fail(job, error.value)
    assert stopped.is_set()
    assert store.get_run(operation["resourceId"])["status"] == "timed_out"
    assert store.get_checkpoint(source["id"]) is None


@pytest.mark.asyncio
async def test_run_and_outbox_rollback_together(client, tmp_path, monkeypatch):
    store, source, operation, job = prepared_run(client)
    store.create_sink(source["id"], cipher=CredentialCipher(tmp_path / "cipher.key"), url="https://hooks.example.com/a", secret="fictional")

    class Runtime:
        async def run(self, source, run, progress):
            return result_for(source, run)

    def unavailable(**kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(store, "enqueue_delivery", unavailable)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        await make_worker(store, Runtime()).process(job)
    assert store.get_run(operation["resourceId"])["status"] == "running"
    assert store.list_items() == []
    assert store.get_checkpoint(source["id"]) is None
    assert store.get_collector(source["id"])["activeOperationId"] == operation["id"]


def test_cancel_queued_run_is_persistent_and_never_claimed(client):
    store, source, operation, job = prepared_run(client)
    with store.transaction() as conn:
        conn.execute("UPDATE jobs SET status='queued', lease_until=NULL WHERE id=?", (job["id"],))
    response = command(client, "POST", f"/api/v1/operations/{operation['id']}/cancel", {}, "cancel-queued-recovery")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert store.get_run(operation["resourceId"])["status"] == "cancelled"
    assert store.get_collector(source["id"])["activeOperationId"] is None
    assert store.claim_job(60) is None
    assert store.verify_audit_chain(app_module.settings.tenant_id)


def test_job_attempt_exhaustion_finishes_the_durable_resources(client):
    store, source, operation, job = prepared_run(client)
    with store.transaction() as conn:
        conn.execute("UPDATE jobs SET attempts=3, lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", job["id"]))
    assert store.claim_job(60) is None
    assert store.get_run(operation["resourceId"])["status"] == "failed"
    assert store.get_operation(operation["id"])["error"]["code"] == "JOB_ATTEMPTS_EXHAUSTED"
    assert store.get_collector(source["id"])["activeOperationId"] is None


@pytest.mark.asyncio
async def test_worker_cancels_inflight_runtime_before_committing(client):
    store, source, operation, job = prepared_run(client)
    started, stopped = asyncio.Event(), asyncio.Event()

    class Runtime:
        async def run(self, source, run, progress):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()

    worker = make_worker(store, Runtime())
    task = asyncio.create_task(worker.process(job))
    await started.wait()
    response = command(client, "POST", f"/api/v1/operations/{operation['id']}/cancel", {}, "cancel-running-recovery")
    assert response.status_code == 200, response.text
    with pytest.raises(RuntimeError, match="cancel") as error:
        await asyncio.wait_for(task, timeout=3)
    worker.fail(job, error.value)
    assert stopped.is_set()
    assert store.get_run(operation["resourceId"])["status"] == "cancelled"
    assert store.list_items() == []


def test_concurrent_claimers_take_one_job_only(client):
    store, source, operation, job = prepared_run(client)
    with store.transaction() as connection:
        connection.execute("UPDATE jobs SET status='queued', lease_until=NULL WHERE id=?", (job["id"],))
    barrier = threading.Barrier(8)

    def claim(_):
        barrier.wait()
        return store.claim_job(60)

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(claim, range(8)))
    assert sum(job is not None for job in claimed) == 1


@pytest.mark.asyncio
async def test_process_kill_recovers_one_result_and_one_outbox_event(client, tmp_path):
    store, source, operation, job = prepared_run(client)
    store.create_sink(source["id"], cipher=CredentialCipher(tmp_path / "cipher.key"), url="https://hooks.example.com/a", secret="fictional")
    with store.transaction() as connection:
        connection.execute("UPDATE jobs SET status='queued', attempts=0, lease_until=NULL WHERE id=?", (job["id"],))
    script = """
import asyncio
from extrio.worker import Worker
class SlowRuntime:
    async def run(self, source, run, progress):
        print("G3_RUNTIME_STARTED", flush=True)
        await asyncio.sleep(60)
async def main():
    worker = Worker()
    worker.runtime = SlowRuntime()
    await worker.serve()
asyncio.run(main())
"""
    env = {
        **os.environ,
        "EXTRIO_DATABASE_URL": store.database_url or "",
        "EXTRIO_DATABASE_PATH": str(store.path),
        "EXTRIO_WORKER_LEASE_SECONDS": "2",
        "EXTRIO_ARTIFACT_PATH": str(tmp_path / "child-artifacts"),
        "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": str(tmp_path / "cipher.key"),
        "EXTRIO_SIGNING_PRIVATE_KEY_PATH": str(tmp_path / "unused-signing.key"),
        "EXTRIO_SEED_DEMO": "false",
    }
    log = tmp_path / "killed-worker.log"
    with log.open("w") as output:
        process = await asyncio.to_thread(
            subprocess.Popen, [sys.executable, "-c", script], env=env, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            deadline = time.monotonic() + 20
            while "G3_RUNTIME_STARTED" not in log.read_text():
                assert process.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()
                await asyncio.sleep(0.05)
            assert store.get_run(operation["resourceId"])["status"] == "running"
            process.kill()
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    assert store.list_items() == []
    assert store.list_deliveries_for_collector(source["id"]) == []
    await asyncio.sleep(2.1)
    replacement = store.claim_job(60)
    assert replacement and replacement["attempts"] == 2

    class Runtime:
        async def run(self, source, run, progress):
            return result_for(source, run)

    worker = make_worker(store, Runtime())
    await worker.process(replacement)
    assert len(store.list_items()) == 1
    assert len(store.list_deliveries_for_collector(source["id"])) == 1
    assert store.get_checkpoint(source["id"])["lastSuccessfulRunId"] == operation["resourceId"]
    # A late stale failure and a duplicate job record cannot reopen a committed result.
    worker.fail(job, RuntimeError("late failure"))
    with store.transaction() as connection:
        connection.execute("UPDATE jobs SET status='queued', lease_until=NULL WHERE id=?", (job["id"],))
    assert store.claim_job(60) is None
    assert store.get_run(operation["resourceId"])["status"] == "succeeded"
    assert len(store.list_items()) == 1
    assert len(store.list_deliveries_for_collector(source["id"])) == 1
