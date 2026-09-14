"""Requirement drafts are separate from immutable execution contracts."""

import copy
import re
from typing import Any

FIELD_TYPES = {"string", "number", "integer", "boolean", "date", "datetime", "url", "html", "object", "array"}

DEFAULT_COLLECTION_FIELDS: list[dict[str, Any]] = [
    {
        "key": "title",
        "label": "公告标题",
        "type": "string",
        "required": True,
        "identity": True,
        "fingerprint": True,
        "description": "采购公告或变更公告的标准标题",
    },
    {
        "key": "publishedAt",
        "label": "发布时间",
        "type": "string",
        "required": True,
        "identity": False,
        "fingerprint": False,
        "description": "公告发布的原始时间或标准日期",
    },
    {
        "key": "buyer",
        "label": "采购人",
        "type": "string",
        "required": False,
        "identity": False,
        "fingerprint": False,
        "description": "招标单位或业主名称",
    },
    {
        "key": "budget",
        "label": "预算金额",
        "type": "string",
        "required": False,
        "identity": False,
        "fingerprint": False,
        "description": "采购预算或最高限价",
    },
    {
        "key": "sourceUrl",
        "label": "详情链接",
        "type": "string",
        "required": True,
        "identity": True,
        "fingerprint": False,
        "description": "详情页的完整访问地址",
    },
    {
        "key": "region",
        "label": "所属地区",
        "type": "string",
        "required": False,
        "identity": False,
        "fingerprint": False,
        "description": "省级行政区或所属城市",
    },
    {
        "key": "content",
        "label": "公告正文",
        "type": "string",
        "required": False,
        "identity": False,
        "fingerprint": False,
        "description": "公告全文的纯文本或 Markdown",
    },
    {
        "key": "category",
        "label": "采购类别",
        "type": "string",
        "required": False,
        "identity": False,
        "fingerprint": False,
        "description": "工程、货物、服务或竞争性磋商等业务分类",
    },
]


def validate_field_draft(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"fields"}:
        raise ValueError("字段草稿必须包含 fields")
    fields = value["fields"]
    if not isinstance(fields, list) or len(fields) > 100:
        raise ValueError("字段草稿最多包含 100 个字段")
    keys = set()
    for field in fields:
        if not isinstance(field, dict) or set(field) != {"key", "label", "type", "required", "identity", "fingerprint", "description"}:
            raise ValueError("字段属性与合同不一致")
        key = field["key"]
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key) or key in keys:
            raise ValueError("字段标识须以英文字母开头，仅含字母、数字、下划线，且不能重复")
        keys.add(key)
        if not isinstance(field["label"], str) or not field["label"].strip() or len(field["label"]) > 100:
            raise ValueError("字段名称须为 1 至 100 个字符")
        if not isinstance(field["description"], str) or len(field["description"]) > 2000:
            raise ValueError("字段说明最多 2000 个字符")
        if not isinstance(field["type"], str) or field["type"] not in FIELD_TYPES:
            raise ValueError("不支持的字段类型")
        if any(type(field[name]) is not bool for name in ("required", "identity", "fingerprint")):
            raise ValueError("必填、去重标识和变更检测必须为布尔值")
        if field["identity"] and not field["required"]:
            raise ValueError("用于去重的字段必须为必填字段")
    return value


def project_source_contract(source: dict, version: dict | None) -> dict:
    active = source.get("activeRuleVersion")
    candidate = source.get("candidate") or {}
    spec = (version or {}).get("gatherSpec") if active else candidate.get("gatherSpec")
    state = ("published" if active else "candidate") if spec else ("unavailable" if active else "empty")
    spec = spec or {}
    contract = spec.get("contract", {})
    schema = contract.get("normalizedItemSchema", {})
    collect = spec.get("collect", {})
    rules = {**collect.get("list", {}).get("fields", {}), **collect.get("detail", {}).get("fields", {})}
    fields = []
    for key, definition in schema.get("properties", {}).items():
        rule = rules.get(key, {})
        schema_type = definition.get("type", "string")
        if isinstance(schema_type, list):
            schema_type = next((item for item in schema_type if item != "null"), "string")
        value_type = rule.get("valueType", schema_type)
        if str(spec.get("collectionVersionRef", {}).get("collectionVersionId", "")).startswith("colver_"):
            # HTML has a string schema without a format; keep its extraction semantics.
            semantic_type = "html" if schema_type == "string" and value_type == "html" else schema_type
            value_type = {"date": "date", "date-time": "datetime", "uri": "url"}.get(definition.get("format"), semantic_type)
        fields.append(
            {
                "key": key,
                "label": rule.get("label") or definition.get("title") or key,
                "type": value_type if value_type in FIELD_TYPES else schema_type,
                "required": key in schema.get("required", []),
                "identity": key in contract.get("identityFields", []),
                "fingerprint": key in contract.get("fingerprintFields", []),
                "description": definition.get("description", ""),
            }
        )
    return {
        "sourceId": source["id"],
        "sourceName": source["name"],
        "state": state,
        "ruleVersion": active or candidate.get("id"),
        "fields": fields,
        "schema": schema,
        "quality": contract.get("quality", {}),
    }


def json_schema_type(value_type: str) -> str | list[str]:
    return {
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "object": "object",
        "array": "array",
        "json": ["object", "array", "string", "number", "boolean", "null"],
    }.get(value_type, "string")


def build_collection_version_contract(draft_fields: list[dict[str, Any]]) -> dict[str, Any]:
    from extrio.contracts import sha256_digest

    validate_field_draft({"fields": draft_fields})
    if not draft_fields:
        raise ValueError("发布版本至少需要包含一个字段")
    identity_fields = [f["key"] for f in draft_fields if f.get("identity")]
    if not 1 <= len(identity_fields) <= 16:
        raise ValueError("发布版本需要 1 至 16 个去重标识（identity）字段")
    fingerprint_fields = [f["key"] for f in draft_fields if f.get("fingerprint")]
    if not 1 <= len(fingerprint_fields) <= 64:
        raise ValueError("发布版本需要 1 至 64 个变更检测（fingerprint）字段")

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            field["key"]: {
                "type": json_schema_type(field["type"]) if field["required"] else [json_schema_type(field["type"]), "null"],
                "title": field["label"],
                **({"minLength": 1} if field["required"] and json_schema_type(field["type"]) == "string" else {}),
                **(
                    {"format": {"date": "date", "datetime": "date-time", "url": "uri"}[field["type"]]}
                    if field["type"] in {"date", "datetime", "url"}
                    else {}
                ),
                **({"description": field["description"]} if field.get("description") else {}),
            }
            for field in draft_fields
        },
        "required": [field["key"] for field in draft_fields if field.get("required")],
        "additionalProperties": False,
    }
    return {
        "fields": copy.deepcopy(draft_fields),
        "normalizedItemSchema": schema,
        "identityFields": identity_fields,
        "fingerprintFields": fingerprint_fields,
        "outputContractDigest": sha256_digest(
            {"normalizedItemSchema": schema, "identityFields": identity_fields, "fingerprintFields": fingerprint_fields}
        ),
    }


def constrain_rule_plan(plan: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
    """Only extraction mechanics come from the model; field semantics come from the version."""
    plan = copy.deepcopy(plan)
    fields = {field["key"]: field for field in version["fields"]}
    stages = [plan["list"]] + ([plan["detail"]] if plan["mode"] == "list_detail" else [])
    available = {key for stage in stages for key in stage["fields"]}
    missing = fields.keys() - available
    if missing:
        raise ValueError("Frozen collection fields missing from rule: " + ", ".join(sorted(missing)))
    for stage in stages:
        for key in list(stage["fields"]):
            if key not in fields:
                if stage is plan["list"] and plan["mode"] == "list_detail" and key == "detailUrl":
                    continue
                del stage["fields"][key]
                continue
            field, rule = fields[key], stage["fields"][key]
            rule.update(
                label=field["label"][:64],
                required=field["required"],
                valueType={"date": "string", "object": "json", "array": "json"}.get(field["type"], field["type"]),
                onError="reject_item" if field["required"] else "null",
            )
            if field["type"] == "datetime":
                rule.setdefault("datetimeFormat", "RFC3339")
                rule.setdefault("defaultTimezone", "UTC")
            else:
                rule.pop("datetimeFormat", None)
                rule.pop("defaultTimezone", None)
    plan["identityFields"] = list(version["identityFields"])
    plan["fingerprintFields"] = list(version["fingerprintFields"])
    plan["bindings"] = {
        role: binding
        for role, binding in plan["bindings"].items()
        if binding.split(".", 1)[-1] in fields or binding == "list.detailUrl" and plan["mode"] == "list_detail"
    }
    return plan
