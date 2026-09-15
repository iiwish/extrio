from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from extrio.store import TERMINAL_OPERATION_STATUSES, utc_now


class JobLeaseLost(RuntimeError):
    code = "JOB_LEASE_LOST"


class JobCancelled(RuntimeError):
    code = "JOB_CANCELLED"


class JobTimedOut(RuntimeError):
    code = "JOB_TIMED_OUT"


@contextmanager
def owned_transaction(store, job, *, allow_cancel=False):
    with store.transaction() as connection:
        suffix = " FOR UPDATE" if store.dialect.name == "postgresql" else ""
        row = connection.execute("SELECT * FROM jobs WHERE id=?" + suffix, (job["id"],)).fetchone()
        if (
            not row
            or row["status"] != "processing"
            or row["attempts"] != job["attempts"]
            or not row["lease_until"]
            or row["lease_until"] <= utc_now()
        ):
            raise JobLeaseLost("job lease is no longer owned by this attempt")
        operation = store.get_operation(job["operationId"], connection)
        if not operation or operation["status"] in TERMINAL_OPERATION_STATUSES:
            raise JobLeaseLost("job lease operation is already terminal")
        if operation.get("cancelRequested") and not allow_cancel:
            raise JobCancelled("job cancellation requested")
        yield connection


def renew_job(store, job):
    with owned_transaction(store, job) as connection:
        until = (datetime.now(UTC) + timedelta(seconds=job["leaseSeconds"])).isoformat().replace("+00:00", "Z")
        connection.execute("UPDATE jobs SET lease_until=? WHERE id=?", (until, job["id"]))


def finish_resources(store, connection, job, error, *, status="failed"):
    from extrio.collection_workflows import lock_collector

    collector_id = job["payload"].get("collectorId")
    if collector_id:
        lock_collector(store, connection, collector_id)
    operation = store.get_operation(job["operationId"], connection)
    if not operation or operation["status"] in TERMINAL_OPERATION_STATUSES:
        return
    ai_run_id = job["payload"].get("aiRunId")
    if ai_run_id:
        store.update_ai_activity(
            job["operationId"], ai_run_id, status=status, phase="completed", progress=100, error=error, connection=connection
        )
        ai_run = store.get_ai_run(ai_run_id, connection)
        started = ai_run.get("startedAt") or ai_run["createdAt"]
        store.update_ai_run(
            ai_run_id,
            connection=connection,
            finishedAt=utc_now(),
            durationMs=max(0, int((datetime.now(UTC) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds() * 1000)),
            resultStatus="no_candidate",
            reviewStatus="not_ready",
        )
        for row in connection.execute("SELECT id, data FROM ai_attempts WHERE ai_run_id=?", (ai_run_id,)).fetchall():
            if store.dialect.decode_json(row["data"])["status"] == "running":
                store.finish_ai_attempt(row["id"], status=status, error=error, connection=connection)
    else:
        operation.update(status=status, phase="completed", progress=100, error=error)
        store.save_operation(operation, collector_id, connection)
    collector = store.get_collector(collector_id, connection) if collector_id else None
    if collector and collector.get("activeOperationId") == job["operationId"]:
        collector["activeOperationId"] = None
        if job["kind"] == "explore":
            collector["status"] = job["payload"].get("previousStatus", "draft")
            if collector.get("collectionMigration"):
                collector["collectionMigration"] = {**collector["collectionMigration"], "status": "failed"}
        store.save_collector(collector, connection)
    run_id = job["payload"].get("runId")
    run = store.get_run(run_id, connection) if run_id else None
    if run:
        run.update(status=status, duration="-", summary=error["message"], recoveryAction="Review the failure and retry.")
        if error["code"].startswith("INTEGRITY"):
            run["integrityStatus"] = "invalid"
        store.save_run(run, connection)
    connection.execute("UPDATE jobs SET status='failed', lease_until=NULL, last_error=? WHERE id=?", (error["message"][:2000], job["id"]))


def request_cancel(store, operation_id, audit):
    with store.transaction() as connection:
        suffix = " FOR UPDATE" if store.dialect.name == "postgresql" else ""
        row = connection.execute("SELECT * FROM jobs WHERE operation_id=?" + suffix, (operation_id,)).fetchone()
        operation = store.get_operation(operation_id, connection)
        if not row or not operation:
            raise KeyError(operation_id)
        if operation["status"] in TERMINAL_OPERATION_STATUSES or operation.get("cancelRequested"):
            return operation
        operation["cancelRequested"] = True
        store.save_operation(operation, store.operation_collector_id(operation_id, connection), connection)
        if row["status"] == "queued" or not row["lease_until"] or row["lease_until"] <= utc_now():
            job = {"id": row["id"], "kind": row["kind"], "operationId": operation_id, "payload": store.dialect.decode_json(row["payload"])}
            finish_resources(
                store,
                connection,
                job,
                {
                    "code": "JOB_CANCELLED",
                    "message": "Job cancelled",
                    "retryable": False,
                    "requestId": audit["requestId"],
                    "pointer": None,
                    "details": {},
                },
                status="cancelled",
            )
        store._append_audit_event(
            connection,
            tenant_id=audit["tenantId"],
            target_type="Operation",
            target_id=operation_id,
            audit={**audit, "action": "operation.cancel"},
            before_digest=None,
            after_digest=None,
        )
        return store.get_operation(operation_id, connection)
