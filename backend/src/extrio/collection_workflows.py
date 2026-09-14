"""Reviewed collection changes, with receipts and audit in the mutation transaction."""

import copy
import hashlib
from typing import Any

from extrio.collection_fields import project_source_contract
from extrio.store import IdempotencyConflict, payload_hash, utc_now


def lock_collector(store, connection, collector_id):
    from extrio.collector_lifecycle import LifecycleError

    suffix = " FOR UPDATE" if store.dialect.name == "postgresql" else ""
    if not connection.execute("SELECT id FROM collectors WHERE id=?" + suffix, (collector_id,)).fetchone():
        raise LifecycleError("COLLECTOR_NOT_FOUND")
    if connection.execute("SELECT 1 FROM deleted_collectors WHERE id=?", (collector_id,)).fetchone():
        raise LifecycleError("COLLECTOR_NOT_FOUND")


def receipt(store, connection, scope, key, body):
    if store.dialect.name == "postgresql":
        lock_id = int.from_bytes(hashlib.sha256(f"{scope}:{key}".encode()).digest()[:8], signed=True)
        connection.execute("SELECT pg_advisory_xact_lock(?)", (lock_id,))
    row = connection.execute("SELECT * FROM idempotency WHERE scope=? AND key=?", (scope, key)).fetchone()
    if row:
        if row["request_hash"] != payload_hash(body):
            raise IdempotencyConflict(key)
        return row["status_code"], store.dialect.decode_json(row["response"]), True
    return None


def finish_command(store, connection, scope, key, body, value, status, audit, target_type, target_id, action):
    store._append_audit_event(
        connection,
        tenant_id=audit["tenantId"],
        target_type=target_type,
        target_id=target_id,
        audit={**audit, "action": action},
        before_digest=None,
        after_digest=f"sha256:{payload_hash(value)}",
    )
    connection.execute(
        "INSERT INTO idempotency(scope, key, request_hash, status_code, response, created_at) VALUES(?, ?, ?, ?, ?, ?)",
        (scope, key, payload_hash(body), status, store.dialect.json_param(value), utc_now()),
    )
    return status, value, False


def migration_plan(store, collector_id: str, target_version_id: str, connection=None) -> dict[str, Any]:
    if connection is None:
        with store.connect() as conn:
            return migration_plan(store, collector_id, target_version_id, conn)
    source = store.get_collector(collector_id, connection)
    if source is None:
        raise ValueError("COLLECTOR_NOT_FOUND")
    target = store.get_collection_version(target_version_id, connection)
    if target is None or target["collectionId"] != source.get("collectionId"):
        raise ValueError("VERSION_NOT_FOUND")
    collection = store.get_collection(source["collectionId"], connection)
    rule = store.get_rule_version(source["activeRuleVersion"], connection) if source.get("activeRuleVersion") else None
    bound = store.get_collection_version(source["collectionVersion"], connection)
    old_fields = bound["fields"] if bound else project_source_contract(source, rule)["fields"]
    before = {field["key"]: field for field in old_fields}
    after = {field["key"]: field for field in target["fields"]}
    changes = []
    for field in sorted(before.keys() | after.keys()):
        old, new = before.get(field), after.get(field)
        if old != new:
            changes.append(
                {
                    "key": field,
                    "kind": "added" if old is None else "removed" if new is None else "changed",
                    "before": old,
                    "after": new,
                    "breaking": bool(old and (new is None or any(old.get(k) != new.get(k) for k in ("type", "identity", "fingerprint"))))
                    or bool(new and new["required"] and (not old or not old["required"])),
                }
            )
    blockers = []
    if source.get("lifecycle", "active") == "archived":
        blockers.append("COLLECTOR_ARCHIVED")
    if collection["status"] == "archived":
        blockers.append("COLLECTION_ARCHIVED")
    if source.get("pendingCollectionVersion"):
        blockers.append("MIGRATION_ALREADY_ACTIVE")
    if source["collectionVersion"] == target_version_id:
        blockers.append("VERSION_ALREADY_BOUND")
    if store.has_active_run(collector_id, connection):
        blockers.append("RUN_ALREADY_ACTIVE")
    operation = store.get_operation(source.get("activeOperationId"), connection) if source.get("activeOperationId") else None
    if operation and operation["status"] not in {"succeeded", "failed", "cancelled", "timed_out"}:
        blockers.append("OPERATION_ALREADY_ACTIVE")
    digest_input = {
        "source": {
            k: source.get(k)
            for k in (
                "id",
                "collectionId",
                "collectionVersion",
                "activeRuleVersion",
                "status",
                "intent",
                "sourceUrl",
                "candidate",
                "pendingCollectionVersion",
            )
        },
        "target": target,
        "collectionRevision": collection["revision"],
    }
    return {
        "collectorId": collector_id,
        "fromVersionId": source["collectionVersion"],
        "targetVersionId": target_version_id,
        "targetVersionNumber": target["versionNumber"],
        "changes": changes,
        "blockers": blockers,
        "requiresRecompile": True,
        "planDigest": f"sha256:{payload_hash(digest_input)}",
    }


def migration_command(store, collector_id, body, key, audit, *, cancel=False):
    scope = f"POST:/collectors/{collector_id}/collection-migration" + ("/cancel" if cancel else "")
    with store.transaction() as connection:
        if found := receipt(store, connection, scope, key, body):
            return found
        lock_collector(store, connection, collector_id)
        source = store.get_collector(collector_id, connection)
        from extrio.collector_lifecycle import require_active

        require_active(source)
        if cancel:
            row = connection.execute("SELECT data FROM collection_migrations WHERE collector_id=?", (collector_id,)).fetchone()
            previous = store._decode(row)
            if not previous or source.get("pendingCollectionVersion") != body["targetVersionId"]:
                raise ValueError("MIGRATION_NOT_ACTIVE")
            active = store.get_operation(source.get("activeOperationId"), connection) if source.get("activeOperationId") else None
            if active and active["status"] not in {"succeeded", "failed", "cancelled", "timed_out"}:
                raise ValueError("OPERATION_ALREADY_ACTIVE")
            definition = previous.get("definition")
            if definition and all(source.get(key) == value for key, value in definition.items()):
                source.update(previous["snapshot"])
            else:
                source.update(status="draft", candidate=None, previewItems=[], reviewDecisions=None)
            source.update(pendingCollectionVersion=None, collectionMigration=None, activeOperationId=None)
            connection.execute("DELETE FROM collection_migrations WHERE collector_id=?", (collector_id,))
        else:
            plan = migration_plan(store, collector_id, body["targetVersionId"], connection)
            if plan["blockers"]:
                raise ValueError(plan["blockers"][0])
            if plan["planDigest"] != body["planDigest"]:
                raise ValueError("MIGRATION_CONFLICT")
            if sorted(body["confirmedChanges"]) != sorted(change["key"] for change in plan["changes"]):
                raise ValueError("MIGRATION_REVIEW_REQUIRED")
            snapshot = {key: copy.deepcopy(source.get(key)) for key in ("status", "candidate", "previewItems", "reviewDecisions")}
            migration = {
                "fromVersionId": source["collectionVersion"],
                "targetVersionId": body["targetVersionId"],
                "targetVersionNumber": plan["targetVersionNumber"],
                "status": "awaiting_compile",
                "startedAt": utc_now(),
            }
            connection.execute(
                "INSERT INTO collection_migrations(collector_id, data) VALUES(?, ?) "
                "ON CONFLICT(collector_id) DO UPDATE SET data=excluded.data",
                (
                    collector_id,
                    store.dialect.json_param(
                        {**migration, "snapshot": snapshot, "definition": {key: source.get(key) for key in ("intent", "sourceUrl")}}
                    ),
                ),
            )
            source.update(
                pendingCollectionVersion=body["targetVersionId"], collectionMigration=migration, status="draft", reviewDecisions=None
            )
        store.save_collector(source, connection)
        return finish_command(
            store,
            connection,
            scope,
            key,
            body,
            source,
            200,
            audit,
            "collector",
            collector_id,
            "collection_migration.cancelled" if cancel else "collection_migration.started",
        )
