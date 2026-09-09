"""Requirement drafts are separate from immutable execution contracts."""
import re
from typing import Any

FIELD_TYPES = {"string", "number", "integer", "boolean", "date", "datetime", "url", "html", "object", "array"}


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
        fields.append({"key": key, "label": rule.get("label") or definition.get("title") or key,
                       "type": value_type if value_type in FIELD_TYPES else schema_type,
                       "required": key in schema.get("required", []),
                       "identity": key in contract.get("identityFields", []),
                       "fingerprint": key in contract.get("fingerprintFields", []),
                       "description": definition.get("description", "")})
    return {"sourceId": source["id"], "sourceName": source["name"], "state": state,
            "ruleVersion": active or candidate.get("id"), "fields": fields,
            "schema": schema, "quality": contract.get("quality", {})}
