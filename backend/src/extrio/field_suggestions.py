"""Durable, bounded field suggestions. Model output never publishes a contract."""

import copy
import uuid
from datetime import UTC, datetime, timedelta

from extrio.collection_fields import validate_field_draft
from extrio.collection_workflows import finish_command, receipt
from extrio.store import stable_id, utc_now


def _field(key, label, value_type="string", *, required=False, identity=False, fingerprint=True):
    return {
        "key": key,
        "label": label,
        "type": value_type,
        "required": required,
        "identity": identity,
        "fingerprint": fingerprint,
        "description": "",
    }


TEMPLATES = [
    {
        "id": "public_notices_v1",
        "name": "公共公告",
        "version": 1,
        "fields": [
            _field("title", "标题", required=True, identity=True),
            _field("publishedAt", "发布日期", "date", fingerprint=False),
            _field("sourceUrl", "详情链接", "url", fingerprint=False),
            _field("content", "正文"),
        ],
    },
    {
        "id": "product_catalog_v1",
        "name": "产品目录",
        "version": 1,
        "fields": [
            _field("sku", "产品编号", required=True, identity=True, fingerprint=False),
            _field("title", "产品名称", required=True),
            _field("price", "价格", "number"),
            _field("description", "产品说明"),
        ],
    },
    {
        "id": "events_v1",
        "name": "活动日历",
        "version": 1,
        "fields": [
            _field("title", "活动名称", required=True, identity=True),
            _field("date", "活动日期", "date", required=True, identity=True),
            _field("location", "地点"),
            _field("description", "活动说明"),
        ],
    },
]


def suggestion_view(value):
    return {k: v for k, v in value.items() if k != "snapshot"}


def list_suggestions(store, collection_id):
    with store.connect() as connection:
        if store.get_collection(collection_id, connection) is None:
            raise ValueError("COLLECTION_NOT_FOUND")
        return [
            suggestion_view(store._decode(row))
            for row in connection.execute(
                "SELECT data FROM field_suggestions WHERE collection_id=? ORDER BY created_at DESC LIMIT 20", (collection_id,)
            ).fetchall()
        ]


def field_workflow_command(store, collection_id, kind, body, key, audit, suggestion_id=None):
    scope = f"POST:/collections/{collection_id}/{kind}/{suggestion_id or ''}"
    with store.transaction() as connection:
        if found := receipt(store, connection, scope, key, body):
            return found
        store._lock_collection(connection, collection_id)
        collection = store.get_collection(collection_id, connection)
        if collection["status"] == "archived":
            raise ValueError("COLLECTION_ARCHIVED")
        if collection["revision"] != body["revision"]:
            raise ValueError("COLLECTION_CONFLICT")
        if kind == "field-suggestions":
            if connection.execute(
                "SELECT id FROM field_suggestions WHERE collection_id=? AND status IN ('queued', 'running')", (collection_id,)
            ).fetchone():
                raise ValueError("SUGGESTION_ALREADY_ACTIVE")
            since = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            count = connection.execute(
                "SELECT COUNT(*) AS total FROM field_suggestions WHERE collection_id=? AND created_at>=?", (collection_id, since)
            ).fetchone()["total"]
            if count >= 5:
                raise ValueError("SUGGESTION_RATE_LIMIT")
            suggestion_id = stable_id("field_suggestion", uuid.uuid4().hex, 32)
            snapshot = {
                "name": collection["name"],
                "intent": collection["intent"][:4000],
                "fields": [
                    {**field, "description": field["description"][:300]}
                    for field in (collection.get("fieldDraft") or {}).get("fields", [])[:50]
                ],
            }
            value = {
                "id": suggestion_id,
                "collectionId": collection_id,
                "baseRevision": collection["revision"],
                "status": "queued",
                "fields": [],
                "error": None,
                "attempt": 0,
                "createdAt": utc_now(),
                "finishedAt": None,
                "appliedAt": None,
                "modelInvocations": [],
                "snapshot": snapshot,
            }
            connection.execute(
                "INSERT INTO field_suggestions(id, collection_id, status, created_at, data) VALUES(?, ?, 'queued', ?, ?)",
                (suggestion_id, collection_id, value["createdAt"], store.dialect.json_param(value)),
            )
            return finish_command(
                store,
                connection,
                scope,
                key,
                body,
                suggestion_view(value),
                202,
                audit,
                "field_suggestion",
                suggestion_id,
                "field_suggestion.requested",
            )
        if kind == "apply-template":
            template = next((item for item in TEMPLATES if item["id"] == body["templateId"]), None)
            if template is None:
                raise ValueError("TEMPLATE_NOT_FOUND")
            fields = copy.deepcopy(template["fields"])
        else:
            suffix = " FOR UPDATE" if store.dialect.name == "postgresql" else ""
            row = connection.execute(
                "SELECT data FROM field_suggestions WHERE id=? AND collection_id=?" + suffix, (suggestion_id, collection_id)
            ).fetchone()
            suggestion = store._decode(row)
            if not suggestion:
                raise ValueError("SUGGESTION_NOT_FOUND")
            if suggestion["status"] != "succeeded" or suggestion["appliedAt"]:
                raise ValueError("SUGGESTION_NOT_READY")
            if suggestion["baseRevision"] != collection["revision"]:
                raise ValueError("COLLECTION_CONFLICT")
            selected = body["selectedKeys"]
            available = {field["key"]: field for field in suggestion["fields"]}
            if not selected or len(selected) != len(set(selected)) or any(key not in available for key in selected):
                raise ValueError("SUGGESTION_SELECTION_INVALID")
            merged = {field["key"]: field for field in (collection.get("fieldDraft") or {}).get("fields", [])}
            merged.update({key: available[key] for key in selected})
            fields = list(merged.values())
            suggestion["appliedAt"] = utc_now()
            connection.execute("UPDATE field_suggestions SET data=? WHERE id=?", (store.dialect.json_param(suggestion), suggestion_id))
        validate_field_draft({"fields": fields})
        value = store.change_collection(collection_id, collection["revision"], {"fieldDraft": {"fields": fields}}, connection)
        return finish_command(
            store,
            connection,
            scope,
            key,
            body,
            value,
            200,
            audit,
            "collection",
            collection_id,
            "collection.template_applied" if kind == "apply-template" else "collection.suggestion_applied",
        )


def claim_suggestion(store):
    now = utc_now()
    with store.transaction() as connection:
        suffix = " FOR UPDATE SKIP LOCKED" if store.dialect.name == "postgresql" else ""
        row = connection.execute(
            "SELECT * FROM field_suggestions WHERE status='queued' OR (status='running' AND lease_until<?) ORDER BY created_at LIMIT 1"
            + suffix,
            (now,),
        ).fetchone()
        if row is None:
            return None
        value = store._decode(row)
        if row["attempt"] >= 3:
            value.update(
                status="failed",
                finishedAt=now,
                error={"code": "SUGGESTION_ATTEMPTS_EXHAUSTED", "message": "字段建议任务重试次数已用完，请重新生成"},
            )
            connection.execute(
                "UPDATE field_suggestions SET status='failed', data=? WHERE id=?", (store.dialect.json_param(value), row["id"])
            )
            return None
        attempt = row["attempt"] + 1
        value.update(status="running", attempt=attempt)
        lease_until = (datetime.now(UTC) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
        connection.execute(
            "UPDATE field_suggestions SET status='running', attempt=?, lease_until=?, data=? WHERE id=?",
            (attempt, lease_until, store.dialect.json_param(value), row["id"]),
        )
        return {
            "id": row["id"],
            "operationId": row["id"],
            "kind": "field_suggestion",
            "payload": {"collectionId": value["collectionId"], "snapshot": value["snapshot"], "attempt": attempt},
        }


def finish_suggestion(store, job, *, fields=None, error=None):
    if error is None:
        validate_field_draft({"fields": fields})
        if not fields or len(fields) > 32:
            raise ValueError("Suggestion must contain between 1 and 32 fields")
    with store.transaction() as connection:
        suffix = " FOR UPDATE" if store.dialect.name == "postgresql" else ""
        row = connection.execute("SELECT * FROM field_suggestions WHERE id=?" + suffix, (job["id"],)).fetchone()
        if row is None or row["status"] != "running" or row["attempt"] != job["payload"]["attempt"]:
            return False
        value = store._decode(row)
        value.update(status="failed" if error else "succeeded", fields=[] if error else fields, error=error, finishedAt=utc_now())
        connection.execute(
            "UPDATE field_suggestions SET status=?, lease_until=NULL, data=? WHERE id=?",
            (value["status"], store.dialect.json_param(value), job["id"]),
        )
        return True


def record_suggestion_invocation(store, suggestion_id, attempt, invocation):
    with store.transaction() as connection:
        suffix = " FOR UPDATE" if store.dialect.name == "postgresql" else ""
        row = connection.execute("SELECT data FROM field_suggestions WHERE id=?" + suffix, (suggestion_id,)).fetchone()
        if row is None:
            raise ValueError("SUGGESTION_NOT_FOUND")
        value = store._decode(row)
        value["modelInvocations"].append({**invocation, "attempt": attempt})
        connection.execute("UPDATE field_suggestions SET data=? WHERE id=?", (store.dialect.json_param(value), suggestion_id))
