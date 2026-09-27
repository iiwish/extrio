"""Versioned, restartable compatibility work for the offline migration command."""

from extrio.collector_history import attribution, rule_attribution, save_attribution
from extrio.store import DEFAULT_COLLECTION_ID, DEFAULT_COLLECTION_NAME, empty_operation_metrics, utc_now

BATCH_SIZE = 200
MIGRATION_ID = "runtime_compatibility_v1"


def record_batches(store, table, *, active_sources=False):
    if table not in {"collectors", "operations", "runs", "items", "ai_runs"}:
        raise ValueError("unsupported backfill table")
    last_id = ""
    predicate = " AND id NOT IN (SELECT id FROM deleted_collectors)" if active_sources else ""
    while True:
        with store.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE id>?{predicate} ORDER BY id LIMIT ?", (last_id, BATCH_SIZE),
            ).fetchall()
        if not rows:
            return
        yield rows
        last_id = rows[-1]["id"]


def compatibility_payload(table, value):
    value = dict(value)
    if table == "collectors":
        value.setdefault("collectionId", DEFAULT_COLLECTION_ID)
        value.setdefault("collectionName", DEFAULT_COLLECTION_NAME)
    elif table == "operations":
        value["metrics"] = {**empty_operation_metrics(), **value.get("metrics", {})}
    elif table == "items":
        value.setdefault("changeType", None)
    elif table == "runs":
        for key in ("recordsOutsideWindow", "duplicateDetailUrls", "newItems", "updatedItems", "unchangedItems"):
            value.setdefault(key, 0)
        value.setdefault("policyContextStatus", "fixed" if value.get("policyVersion") else "legacy_unavailable")
        for key in ("policyVersion", "policyDigest", "executionMode", "windowStart", "checkpointBefore", "checkpointAfter"):
            value.setdefault(key, None)
        if "items" in value:
            value["items"] = [{"changeType": None, **item} for item in value["items"]]
    return value


def backfill_payloads(store):
    for table in ("collectors", "operations", "runs", "items"):
        for rows in record_batches(store, table, active_sources=table == "collectors"):
            with store.transaction() as connection:
                for row in rows:
                    original = store.dialect.decode_json(row["data"])
                    value = compatibility_payload(table, original)
                    if value != original:
                        # Preserve original timestamps and frozen ownership; only add compatibility fields.
                        connection.execute(f"UPDATE {table} SET data=? WHERE id=?", (store.dialect.json_param(value), row["id"]))


def backfill_history(store):
    for kind, table in (("run", "runs"), ("ai_run", "ai_runs"), ("operation", "operations")):
        for rows in record_batches(store, table):
            with store.transaction() as connection:
                for row in rows:
                    if connection.execute(
                        "SELECT 1 FROM source_history_ownership WHERE resource_type=? AND resource_id=?", (kind, row["id"]),
                    ).fetchone():
                        continue
                    source = store.get_collector(row["collector_id"], connection)
                    if source is None:
                        continue
                    value = store.dialect.decode_json(row["data"])
                    rule_id = value.get("ruleVersion") if kind == "run" else value.get("publishedRuleVersionId")
                    owner = rule_attribution(store, connection, store.get_rule_version(rule_id, connection)) if rule_id else None
                    if kind == "operation":
                        for parent_kind, parent_table in (("run", "runs"), ("ai_run", "ai_runs")):
                            operation_id = store.dialect.json_extract_text("parent.data", "operationId")
                            parent = connection.execute(
                                f"SELECT owner.data FROM {parent_table} parent JOIN source_history_ownership owner "
                                "ON owner.resource_id=parent.id AND owner.resource_type=? "
                                f"WHERE parent.collector_id=? AND {operation_id}=? LIMIT 1",
                                (parent_kind, source["id"], row["id"]),
                            ).fetchone()
                            if parent:
                                owner = store._decode(parent)
                                break
                    if owner is None and kind != "run" and not source.get("hasReassignmentHistory"):
                        owner = attribution(store, connection, source["collectionId"], source["collectionVersion"])
                    save_attribution(store, connection, kind, row["id"], source["id"], owner)


def run_backfills(store, connection, *, migrate):
    if connection.execute("SELECT 1 FROM data_migrations WHERE id=?", (MIGRATION_ID,)).fetchone():
        return
    if not migrate:
        raise RuntimeError("Database data migrations are incomplete; run the migration job before starting runtime services")
    store._backfill_collections()
    backfill_payloads(store)
    after_id = ""
    while True:
        with store.transaction() as batch_connection:
            after_id = store._backfill_ai_runs(batch_connection, after_id=after_id, limit=BATCH_SIZE)
        if after_id is None:
            break
    for rows in record_batches(store, "collectors", active_sources=True):
        for row in rows:
            if store.dialect.decode_json(row["data"]).get("lifecycle", "active") == "active":
                store.ensure_collection_policy(row["id"])
            store.ensure_schedule(row["id"])
    backfill_history(store)
    connection.execute("INSERT INTO data_migrations(id, completed_at) VALUES(?, ?)", (MIGRATION_ID, utc_now()))
