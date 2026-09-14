"""Source management commands with locked previews and durable receipts."""

import hashlib

from extrio.collection_fields import DEFAULT_COLLECTION_FIELDS, project_source_contract
from extrio.collection_workflows import finish_command, lock_collector, receipt
from extrio.store import DEFAULT_COLLECTION_POLICY, DEFAULT_COLLECTOR_SCHEDULE, payload_hash, utc_now


class LifecycleError(ValueError):
    @property
    def code(self):
        return str(self)


def require_active(source):
    if source is None or source.get("deletedAt"):
        raise LifecycleError("COLLECTOR_NOT_FOUND")
    if source.get("lifecycle", "active") == "archived":
        raise LifecycleError("COLLECTOR_ARCHIVED")


def lock_source_url(store, connection, source_url):
    if store.dialect.name == "postgresql":
        lock_id = int.from_bytes(hashlib.sha256(f"source-url:{source_url}".encode()).digest()[:8], signed=True)
        connection.execute("SELECT pg_advisory_xact_lock(?)", (lock_id,))


def source_execution_digest(source):
    return payload_hash(
        {
            key: source.get(key)
            for key in (
                "managementRevision",
                "status",
                "activeRuleVersion",
                "collectionId",
                "collectionVersion",
                "pendingCollectionVersion",
                "intent",
                "sourceUrl",
                "candidate",
            )
        }
    )


def active_blockers(store, connection, collector_id):
    status = store.dialect.json_extract_text("data", "status")
    active = any(
        connection.execute(
            f"SELECT 1 FROM {table} WHERE collector_id=? "
            f"AND COALESCE({status}, '') NOT IN ('succeeded', 'failed', 'cancelled', 'timed_out') LIMIT 1",
            (collector_id,),
        ).fetchone()
        for table in ("operations", "ai_runs")
    )
    jobs = connection.execute(
        "SELECT j.id FROM jobs j JOIN operations o ON o.id=j.operation_id "
        "WHERE o.collector_id=? AND j.status IN ('queued', 'processing') LIMIT 1",
        (collector_id,),
    ).fetchone()
    blockers = []
    if jobs or active:
        blockers.append("TASK_ALREADY_ACTIVE")
    if store.has_active_run(collector_id, connection):
        blockers.append("RUN_ALREADY_ACTIVE")
    return blockers


def lifecycle_plan(store, collector_id, connection=None):
    if connection is None:
        with store.transaction() as connection:
            lock_collector(store, connection, collector_id)
            return lifecycle_plan(store, collector_id, connection)
    source = store.get_collector(collector_id, connection)
    if source is None:
        raise LifecycleError("COLLECTOR_NOT_FOUND")
    blockers = active_blockers(store, connection, collector_id)
    if (
        source.get("pendingCollectionVersion")
        or connection.execute("SELECT 1 FROM collection_migrations WHERE collector_id=?", (collector_id,)).fetchone()
    ):
        blockers.append("MIGRATION_ALREADY_ACTIVE")
    history = []
    counts = {}
    for table in (
        "operations",
        "ai_runs",
        "rule_versions",
        "runs",
        "collector_checkpoints",
        "schedule_occurrences",
        "collection_migrations",
        "sinks",
        "deliveries",
        "source_history_ownership",
    ):
        count = int(connection.execute(f"SELECT COUNT(*) AS total FROM {table} WHERE collector_id=?", (collector_id,)).fetchone()["total"])
        if table in {"operations", "ai_runs", "rule_versions", "runs", "sinks", "deliveries"}:
            counts["rules" if table == "rule_versions" else table] = count
        if count:
            history.append("HAS_" + table.upper())
    item_source = store.dialect.json_extract_text("data", "collectorId")
    counts["items"] = int(
        connection.execute(f"SELECT COUNT(*) AS total FROM items WHERE {item_source}=?", (collector_id,)).fetchone()["total"]
    )
    if counts["items"]:
        history.append("HAS_ITEMS")
    policies = connection.execute("SELECT data FROM collection_policies WHERE collector_id=?", (collector_id,)).fetchall()
    if len(policies) > 1 or any(any(store._decode(row).get(k) != v for k, v in DEFAULT_COLLECTION_POLICY.items()) for row in policies):
        history.append("HAS_POLICY_HISTORY")
    if source.get("candidate") or source.get("activeRuleVersion") or source.get("latestRunId"):
        history.append("HAS_SOURCE_HISTORY")
    target_id = store.dialect.json_extract_text("data", "targetId")
    if any(
        store._decode(row).get("action", "").startswith(("collection_migration.", "collector.reassigned"))
        for row in connection.execute(f"SELECT data FROM audit_events WHERE {target_id}=?", (collector_id,)).fetchall()
    ):
        history.append("HAS_MIGRATION_HISTORY")
    schedule = (
        store._decode(connection.execute("SELECT data FROM collector_schedules WHERE collector_id=?", (collector_id,)).fetchone())
        or source.get("schedule")
        or {}
    )
    if schedule.get("enabled") or schedule.get("revision", 1) > 1:
        history.append("HAS_SCHEDULE_HISTORY")
    return {
        "collectorId": collector_id,
        "collectorName": source["name"],
        "sourceUrl": source["sourceUrl"],
        "collectionName": source["collectionName"],
        "lifecycle": source.get("lifecycle", "active"),
        "blockers": blockers,
        "deleteBlockers": list(blockers),
        "hasHistory": bool(history),
        "historyCounts": counts,
        "scheduleEnabled": bool(schedule.get("enabled")),
        "planDigest": "sha256:" + payload_hash({"source": source, "blockers": blockers, "history": history, "counts": counts}),
    }


def disable_schedule(store, connection, source):
    schedule = store._decode(
        connection.execute("SELECT data FROM collector_schedules WHERE collector_id=?", (source["id"],)).fetchone()
    ) or source.get("schedule")
    if schedule and schedule.get("enabled"):
        values = {k: schedule[k] for k in DEFAULT_COLLECTOR_SCHEDULE}
        values["enabled"] = False
        store.save_schedule(source["id"], values, connection)
        source["schedule"] = store.get_collector(source["id"], connection)["schedule"]


def lifecycle_command(store, collector_id, body, key, audit):
    scope = f"POST:/collectors/{collector_id}/lifecycle"
    with store.transaction() as connection:
        if found := receipt(store, connection, scope, key, body):
            return found
        lock_collector(store, connection, collector_id)
        plan = lifecycle_plan(store, collector_id, connection)
        action = body["action"]
        if action not in {"archive", "restore", "delete"}:
            raise LifecycleError("LIFECYCLE_ACTION_INVALID")
        blockers = plan["deleteBlockers"] if action == "delete" else plan["blockers"]
        if blockers:
            raise LifecycleError(blockers[0])
        if plan["planDigest"] != body["planDigest"]:
            raise LifecycleError("COLLECTOR_CONFLICT")
        source = store.get_collector(collector_id, connection)
        if action == "delete":
            from extrio.collector_history import freeze_history, history_snapshot

            lock_source_url(store, connection, source["sourceUrl"])
            freeze_history(store, connection, source, history_snapshot(store, connection, source))
            disable_schedule(store, connection, source)
            # Keep the identity and foreign keys for evidence; the tombstone prevents restoration.
            source.update(lifecycle="archived", updatedAt=utc_now())
            store.save_collector(source, connection, management_write=True)
            connection.execute("INSERT INTO deleted_collectors(id, deleted_at) VALUES(?, ?)", (collector_id, utc_now()))
            value = {"id": collector_id, "deleted": True}
        else:
            disable_schedule(store, connection, source)
            source.update(lifecycle="archived" if action == "archive" else "active", updatedAt=utc_now())
            store.save_collector(source, connection, management_write=True)
            value = source
        return finish_command(store, connection, scope, key, body, value, 200, audit, "collector", collector_id, f"collector.{action}")


def invalidate_execution(store, connection, source):
    disable_schedule(store, connection, source)
    source.update(
        status="draft",
        activeRuleVersion=None,
        candidate=None,
        previewItems=[],
        reviewDecisions=None,
        checkpoint=None,
        activeOperationId=None,
    )
    connection.execute("DELETE FROM collector_checkpoints WHERE collector_id=?", (source["id"],))


def definition_command(store, collector_id, body, key, audit, normalized):
    scope = f"PATCH:/collectors/{collector_id}"
    with store.transaction() as connection:
        if found := receipt(store, connection, scope, key, body):
            return found
        lock_collector(store, connection, collector_id)
        source = store.get_collector(collector_id, connection)
        require_active(source)
        if source.get("managementRevision", 0) != body["managementRevision"]:
            raise LifecycleError("COLLECTOR_CONFLICT")
        if blockers := active_blockers(store, connection, collector_id):
            raise LifecycleError(blockers[0])
        if source.get("pendingCollectionVersion"):
            raise LifecycleError("MIGRATION_ALREADY_ACTIVE")
        lock_source_url(store, connection, normalized["sourceUrl"])
        if store.source_exists(normalized["sourceUrl"], connection, exclude_collector_id=collector_id):
            raise LifecycleError("SOURCE_ALREADY_EXISTS")
        if any(source[k] != normalized[k] for k in ("intent", "sourceUrl")):
            invalidate_execution(store, connection, source)
        source.update(normalized, updatedAt=utc_now())
        store.save_collector(source, connection, management_write=True)
        return finish_command(
            store, connection, scope, key, body, source, 200, audit, "collector", collector_id, "collector.definition_updated"
        )


def reassignment_plan(store, collector_id, target_id, connection=None):
    if connection is None:
        with store.transaction() as connection:
            lock_collector(store, connection, collector_id)
            store._lock_collection(connection, target_id)
            return reassignment_plan(store, collector_id, target_id, connection)
    from extrio.collector_history import history_snapshot

    source = store.get_collector(collector_id, connection)
    target = store.get_collection(target_id, connection)
    if source is None:
        raise LifecycleError("COLLECTOR_NOT_FOUND")
    if target is None:
        raise LifecycleError("COLLECTION_NOT_FOUND")
    lifecycle = lifecycle_plan(store, collector_id, connection)
    blockers = list(lifecycle["blockers"])
    if source.get("lifecycle", "active") == "archived":
        blockers.append("COLLECTOR_ARCHIVED")
    if target["status"] == "archived":
        blockers.append("COLLECTION_ARCHIVED")
    if target_id == source["collectionId"]:
        blockers.append("COLLECTION_ALREADY_BOUND")
    snapshot = history_snapshot(store, connection, source)
    if snapshot["unresolved"]:
        blockers.append("HISTORY_OWNERSHIP_UNRESOLVED")
    rule = store.get_rule_version(source["activeRuleVersion"], connection) if source.get("activeRuleVersion") else None
    version = store.get_collection_version(source["collectionVersion"], connection)
    old_fields = version["fields"] if version else project_source_contract(source, rule)["fields"]
    target_version_id = target.get("activeVersionId") or target["collectionVersion"]
    target_version = store.get_collection_version(target_version_id, connection)
    if target.get("activeVersionId") and (not target_version or target_version["collectionId"] != target_id):
        blockers.append("VERSION_NOT_FOUND")
    new_fields = target_version["fields"] if target_version else DEFAULT_COLLECTION_FIELDS
    before, after = ({field["key"]: field for field in fields} for fields in (old_fields, new_fields))
    changes = [
        {
            "key": field,
            "kind": "added" if field not in before else "removed" if field not in after else "changed",
            "before": before.get(field),
            "after": after.get(field),
        }
        for field in sorted(before.keys() | after.keys())
        if before.get(field) != after.get(field)
    ]
    requires_recompile = lifecycle["hasHistory"]
    if not requires_recompile:
        changes = []
    digest = payload_hash(
        {
            "source": source,
            "lifecycle": lifecycle,
            "target": target,
            "targetVersion": target_version,
            "history": {"counts": snapshot["counts"], "unresolved": snapshot["unresolved"]},
        }
    )
    return {
        "collectorId": collector_id,
        "collectorName": source["name"],
        "sourceUrl": source["sourceUrl"],
        "fromCollectionId": source["collectionId"],
        "fromCollectionName": source["collectionName"],
        "targetCollectionId": target_id,
        "targetCollectionName": target["name"],
        "targetIntent": target["intent"],
        "targetVersionId": target_version_id,
        "targetRevision": target["revision"],
        "changes": changes,
        "blockers": blockers,
        "requiresRecompile": requires_recompile,
        "historyCounts": snapshot["counts"],
        "unresolvedHistory": snapshot["unresolved"],
        "planDigest": "sha256:" + digest,
    }


def reassignment_command(store, collector_id, body, key, audit):
    from extrio.collector_history import freeze_history, history_snapshot

    scope = f"POST:/collectors/{collector_id}/reassignment"
    with store.transaction() as connection:
        if found := receipt(store, connection, scope, key, body):
            return found
        lock_collector(store, connection, collector_id)
        store._lock_collection(connection, body["targetCollectionId"])
        plan = reassignment_plan(store, collector_id, body["targetCollectionId"], connection)
        if plan["blockers"]:
            raise LifecycleError(plan["blockers"][0])
        if plan["planDigest"] != body["planDigest"]:
            raise LifecycleError("COLLECTOR_CONFLICT")
        if sorted(body["confirmedChanges"]) != sorted(change["key"] for change in plan["changes"]):
            raise LifecycleError("REASSIGNMENT_REVIEW_REQUIRED")
        source = store.get_collector(collector_id, connection)
        freeze_history(store, connection, source, history_snapshot(store, connection, source))
        invalidate_execution(store, connection, source)
        source.update(
            collectionId=plan["targetCollectionId"],
            collectionName=plan["targetCollectionName"],
            collectionVersion=plan["targetVersionId"],
            intent=plan["targetIntent"],
            hasReassignmentHistory=True,
            updatedAt=utc_now(),
        )
        store.save_collector(source, connection, management_write=True)
        return finish_command(store, connection, scope, key, body, source, 200, audit, "collector", collector_id, "collector.reassigned")
