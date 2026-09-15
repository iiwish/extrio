"""Numbered reads for the operational workspaces; legacy list APIs stay intact."""

from typing import Any

from extrio.collector_history import history_source


def pagination(total: int, requested: int, limit: int) -> dict[str, int]:
    pages = max(1, (total + limit - 1) // limit)
    return {"page": min(requested, pages), "pageSize": limit, "totalPages": pages, "total": total}


def numbered(values, requested, limit, counts, **metadata):
    info = pagination(len(values), requested, limit)
    start = (info["page"] - 1) * limit
    return {"items": values[start:start + limit], "page": {"nextCursor": None},
            "total": len(values), "pagination": info, "counts": counts, **metadata}


def needs_attention(collector, run):
    if collector.get("lifecycle", "active") == "archived":
        return False
    if collector.get("activeOperationId") or (run and run.get("status") in {"queued", "running", "finalizing"}):
        return False
    return bool(
        (run and run.get("status") in {"failed", "cancelled", "timed_out", "partially_succeeded"})
        or collector.get("pendingCollectionVersion")
        or collector.get("status") in {"draft", "ready_review", "exploring"}
        or not collector.get("activeRuleVersion")
        or not collector.get("latestRunId")
        or (collector.get("latestRunId") and not run)
        or (run and run.get("rejectedCount", 0) > 0)
    )


def collection_page(store, requested, limit, status, q, sort):
    values = store.list_collections()
    counts = {"all": len(values), **{key: sum(row.get("status") == key for row in values) for key in ("active", "archived")}}
    term = (q or "").strip().lower()
    values = [row for row in values if (status == "all" or row["status"] == status)
              and term in f'{row["name"]} {row["intent"]}'.lower()]
    values.sort(key=lambda row: row["id"])
    values.sort(key=lambda row: row["updatedAt"], reverse=sort != "updated_asc")
    result = numbered(values, requested, limit, counts)
    result.pop("page")  # CollectionPage has no legacy cursor envelope.
    return result


def collector_page(store, requested, limit, lifecycle, view, q, collection_id):
    values = [row for row in store.list_collectors() if lifecycle == "all" or row["lifecycle"] == lifecycle]
    runs = {row["latestRunId"]: store.get_run(row["latestRunId"]) for row in values if row.get("latestRunId")}
    attention = {row["id"] for row in values if needs_attention(row, runs.get(row.get("latestRunId")))}
    counts = {"all": len(values), "attention": len(attention), "published": sum(row["status"] == "published" for row in values)}
    collections = {row["collectionId"]: {"id": row["collectionId"], "name": row["collectionName"],
                                         "version": row["collectionVersion"]} for row in values}
    term = (q or "").strip().lower()
    selected = [row for row in values if (not collection_id or row["collectionId"] == collection_id)
                and (view == "all" or (row["id"] in attention if view == "attention" else row["status"] == "published"))
                and term in f'{row["name"]} {row["sourceUrl"]} {row["collectionName"]}'.lower()]
    result = numbered(selected, requested, limit, counts, collections=list(collections.values()))
    result["latestRuns"] = [runs[row["latestRunId"]] for row in result["items"] if runs.get(row.get("latestRunId"))]
    return result


def history_page(store, kind, requested, limit, status, q, collector_id=None):
    table, entity = ("runs", "run") if kind == "runs" else ("ai_runs", "ai_run")
    source = history_source(table, entity)
    def field(key):
        return store.dialect.json_extract_text("data", key)
    state = field("status")
    groups = {"all": "1=1"}
    if kind == "runs":
        groups.update(attention=f"{state} IN ('partially_succeeded', 'failed', 'timed_out')", succeeded=f"{state}='succeeded'")
    else:
        groups.update(running=f"{state} IN ('queued', 'running', 'finalizing')",
                      attention=f"({state}='failed' OR {field('resultStatus')}='no_candidate')",
                      review=f"(collector_deleted_at IS NULL AND {field('reviewStatus')}='ready_review')")
    clauses, params = [], []
    if collector_id:
        clauses.append("collector_id=?")
        params.append(collector_id)
    scope = "WHERE " + " AND ".join(clauses) if clauses else ""
    with store.connect() as connection:
        count_columns = ", ".join(f"SUM(CASE WHEN {expr} THEN 1 ELSE 0 END) AS count_{name}" for name, expr in groups.items())
        counts_row = connection.execute(f"SELECT {count_columns} FROM {source} {scope}", tuple(params)).fetchone()
        counts = {key: int(counts_row[f"count_{key}"] or 0) for key in groups}
        clauses.append(groups[status])
        term = (q or "").strip().lower()
        if term:
            pattern = "%" + term.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            search_fields = [field("collectorName"), "id" if kind == "runs" else field("sourceUrl")]
            clauses.append("(" + " OR ".join(f"LOWER(COALESCE({column}, '')) LIKE ? ESCAPE '!'" for column in search_fields) + ")")
            params.extend([pattern] * len(search_fields))
        where = "WHERE " + " AND ".join(clauses)
        total = int(connection.execute(f"SELECT COUNT(*) AS total FROM {source} {where}", tuple(params)).fetchone()["total"])
        info = pagination(total, requested, limit)
        rows = connection.execute(
            f"SELECT data, created_at, collection_attribution, collector_deleted_at FROM {source} {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, limit, (info["page"] - 1) * limit),
        ).fetchall()
    items: list[dict[str, Any]] = [store._decode_run(row) if kind == "runs" else {"publishedRuleVersionId": None, **store._decode(row)}
                                  for row in rows]
    return {"items": items, "total": total, "pagination": info, "counts": counts, "page": {"nextCursor": None}}
