"""Immutable attribution metadata, separate from original rule/run/item payloads."""


def attribution(store, connection, collection_id, version_id):
    row = connection.execute("SELECT data FROM collections WHERE id=?", (collection_id,)).fetchone()
    collection = store._decode(row)
    if not collection or not version_id:
        return None
    return {"collectionId": collection_id, "collectionName": collection["name"], "collectionVersion": version_id}


def rule_attribution(store, connection, rule):
    ref = (rule or {}).get("gatherSpec", {}).get("collectionVersionRef", {})
    return attribution(store, connection, ref.get("collectionId"), ref.get("collectionVersionId"))


def save_attribution(store, connection, kind, resource_id, collector_id, value):
    if value:
        connection.execute(
            store.dialect.insert_or_ignore(
                "INSERT INTO source_history_ownership(resource_type, resource_id, collector_id, collection_id, data) VALUES(?, ?, ?, ?, ?)"
            ),
            (kind, resource_id, collector_id, value["collectionId"], store.dialect.json_param(value)),
        )


def record_new_history(store, connection, kind, value, collector_id):
    table = {"run": "runs", "ai_run": "ai_runs", "operation": "operations"}[kind]
    if connection.execute(f"SELECT 1 FROM {table} WHERE id=?", (value["id"],)).fetchone():
        return
    from extrio.collection_workflows import lock_collector

    lock_collector(store, connection, collector_id)
    source = store.get_collector(collector_id, connection)
    owner = None
    if kind == "run" and value.get("ruleVersion"):
        owner = rule_attribution(store, connection, store.get_rule_version(value["ruleVersion"], connection))
    owner = owner or attribution(store, connection, source["collectionId"], source["collectionVersion"])
    save_attribution(store, connection, kind, value["id"], collector_id, owner)


def history_snapshot(store, connection, source):
    """Resolve old records before moving; unproven run ownership remains a blocker."""
    collector_id = source["id"]
    saved = {
        (row["resource_type"], row["resource_id"]): store._decode(row)
        for row in connection.execute(
            "SELECT resource_type, resource_id, data FROM source_history_ownership WHERE collector_id=?", (collector_id,)
        ).fetchall()
    }
    owners = dict(saved)
    unresolved = []
    counts = {}
    rules = {
        row["id"]: store._decode(row)
        for row in connection.execute("SELECT id, data FROM rule_versions WHERE collector_id=?", (collector_id,)).fetchall()
    }
    counts["rules"] = len(rules)
    for rule_id, rule in rules.items():
        if not rule_attribution(store, connection, rule):
            unresolved.append({"type": "rule", "id": rule_id})
    operation_owners = {}
    for kind, table in (("run", "runs"), ("ai_run", "ai_runs")):
        rows = connection.execute(f"SELECT id, data FROM {table} WHERE collector_id=?", (collector_id,)).fetchall()
        counts[table] = len(rows)
        for row in rows:
            value = store._decode(row)
            owner = owners.get((kind, row["id"]))
            if owner is None:
                rule_id = value.get("ruleVersion") if kind == "run" else value.get("publishedRuleVersionId")
                owner = rule_attribution(store, connection, rules.get(rule_id))
                # Before the first supported reassignment, unversioned AI work belongs to its source's original requirement.
                if owner is None and kind == "ai_run" and not source.get("hasReassignmentHistory"):
                    owner = attribution(store, connection, source["collectionId"], source["collectionVersion"])
            if owner is None:
                unresolved.append({"type": kind, "id": row["id"]})
            else:
                owners[(kind, row["id"])] = owner
                if value.get("operationId"):
                    operation_owners[value["operationId"]] = owner
    operations = connection.execute("SELECT id, data FROM operations WHERE collector_id=?", (collector_id,)).fetchall()
    counts["operations"] = len(operations)
    for row in operations:
        owner = owners.get(("operation", row["id"])) or operation_owners.get(row["id"])
        if owner is None and not source.get("hasReassignmentHistory"):
            owner = attribution(store, connection, source["collectionId"], source["collectionVersion"])
        if owner is None:
            unresolved.append({"type": "operation", "id": row["id"]})
        else:
            owners[("operation", row["id"])] = owner
    counts["items"] = int(
        connection.execute(
            "SELECT COUNT(*) AS total FROM items i JOIN runs r ON r.id=i.run_id WHERE r.collector_id=?", (collector_id,)
        ).fetchone()["total"]
    )
    for table in ("sinks", "deliveries"):
        counts[table] = int(
            connection.execute(f"SELECT COUNT(*) AS total FROM {table} WHERE collector_id=?", (collector_id,)).fetchone()["total"]
        )
    # Item ownership is inherited from the persisted parent run, never from the source's current requirement.
    item_collector = store.dialect.json_extract_text("i.data", "collectorId")
    bad_items = connection.execute(
        f"SELECT i.id FROM items i LEFT JOIN runs r ON r.id=i.run_id WHERE {item_collector}=? "
        "AND (r.id IS NULL OR r.collector_id<>?) LIMIT 20",
        (collector_id, collector_id),
    ).fetchall()
    unresolved.extend({"type": "item", "id": row["id"]} for row in bad_items)
    return {"owners": owners, "unresolved": unresolved, "counts": counts}


def freeze_history(store, connection, source, snapshot):
    for (kind, resource_id), owner in snapshot["owners"].items():
        save_attribution(store, connection, kind, resource_id, source["id"], owner)


def history_source(table, kind):
    return (
        f"(SELECT recorded.*, owner.data AS collection_attribution, deleted.deleted_at AS collector_deleted_at FROM {table} recorded "
        "LEFT JOIN source_history_ownership owner ON "
        f"owner.resource_type='{kind}' AND owner.resource_id=recorded.id "
        f"LEFT JOIN deleted_collectors deleted ON deleted.id=recorded.collector_id) {table}"
    )


def item_source():
    return (
        "(SELECT recorded.*, owner.data AS collection_attribution, deleted.deleted_at AS collector_deleted_at FROM items recorded "
        "LEFT JOIN source_history_ownership owner ON "
        "owner.resource_type='run' AND owner.resource_id=recorded.run_id "
        "LEFT JOIN runs source_run ON source_run.id=recorded.run_id "
        "LEFT JOIN deleted_collectors deleted ON deleted.id=source_run.collector_id) items"
    )
