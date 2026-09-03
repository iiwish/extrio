import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from jsonpath_ng.ext import parse as parse_jsonpath

from extrio.contracts import ContractBundle, sha256_digest
from extrio.integrity import calculate_rule_digest

FIELD_RULES = {
    "title": ("项目名称", "css:h1.notice-title::text", True),
    "buyer": ("采购单位", 'css:.meta [data-field="buyer"]::text', True),
    "publishedAt": ("发布日期", "css:time[datetime]::attr(datetime)", True),
    "budget": ("预算金额", "css:.notice-budget .amount::text", False),
}

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "default_tender",
    "listItemsSelector": "css:.notice-list > li",
    "listTitleSelector": "css:a.notice-title::text",
    "listPublishedAtSelector": "css:time::attr(datetime)",
    "detailLinkSelector": "css:a.notice-title::attr(href)",
    "detailLinkDisplaySelector": "css:a.notice-title",
    "paginationSelector": "css:a.pagination-next",
    "maxPages": 20,
    "maxItems": 10_000,
    "fieldRules": FIELD_RULES,
    "fieldValueTypes": {"publishedAt": "datetime"},
    "multipleMatchPolicy": "error",
    "regionSelector": 'css:.meta [data-field="region"]::text',
}

PROCUREMENT_INTENTION_PROFILE: dict[str, Any] = {
    "name": "procurement_intention_table",
    "listItemsSelector": "css:.inner-ul > li",
    "listTitleSelector": "css:a[href]::text",
    "listPublishedAtSelector": "css:.datetime::text",
    "detailLinkSelector": "css:a[href]::attr(href)",
    "detailLinkDisplaySelector": "css:a[href]",
    "paginationSelector": "css:.fenye_ul > li:nth-last-of-type(3) > a",
    "maxPages": 20,
    "maxItems": 300,
    "fieldRules": {
        # The source emits invalid <h1><p> markup. Browser/Parsel normalization
        # reparents the paragraph beside h1, so anchor the title to the header
        # container instead of relying on the invalid nesting.
        "title": ("公告标题", "css:.xl-box-t p::text", True),
        "publishedAt": ("发布时间", "css:.xl-box-t > span::text", True),
        "content": ("公告正文", "css:#BodyLabel::text", True),
    },
    "fieldValueTypes": {},
    "multipleMatchPolicy": "first",
    "regionSelector": "",
}


def detect_profile(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one(".inner-ul > li a[href]") and soup.select_one(".fenye_ul"):
        return PROCUREMENT_INTENTION_PROFILE
    return DEFAULT_PROFILE


def now_display() -> str:
    return datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")


def selector_value(node: BeautifulSoup | Tag, selector: str, base_url: str) -> str:
    raw = selector.removeprefix("css:")
    attribute = None
    if "::attr(" in raw:
        raw, attribute = raw.rsplit("::attr(", 1)
        attribute = attribute.rstrip(")")
    elif raw.endswith("::text"):
        raw = raw.removesuffix("::text")
        attribute = "__text__"
    elif raw.endswith("::html"):
        raw = raw.removesuffix("::html")
        attribute = "__html__"
    selected = node.select_one(raw)
    if selected is None:
        return ""
    if attribute == "__text__":
        return selected.get_text(" ", strip=True)
    if attribute == "__html__":
        return selected.decode_contents()
    if attribute:
        value = str(selected.get(attribute, "")).strip()
        return urljoin(base_url, value) if attribute in {"href", "src"} else value
    return selected.get_text(" ", strip=True)


def selector_values(node: BeautifulSoup | Tag, selector: str, base_url: str) -> list[str]:
    raw = selector.removeprefix("css:")
    attribute = None
    if "::attr(" in raw:
        raw, attribute = raw.rsplit("::attr(", 1)
        attribute = attribute.rstrip(")")
    elif raw.endswith("::text"):
        raw = raw.removesuffix("::text")
        attribute = "__text__"
    elif raw.endswith("::html"):
        raw = raw.removesuffix("::html")
        attribute = "__html__"

    values: list[str] = []
    for selected in node.select(raw):
        if attribute == "__text__":
            value = selected.get_text(" ", strip=True)
        elif attribute == "__html__":
            value = selected.decode_contents()
        elif attribute:
            value = str(selected.get(attribute, "")).strip()
            if attribute in {"href", "src"}:
                value = urljoin(base_url, value)
        else:
            value = selected.get_text(" ", strip=True)
        if value:
            values.append(value)
    return values


def jsonpath_values(node: Any, selector: str) -> list[Any]:
    expression = selector.removeprefix("jsonpath:")
    return [match.value for match in parse_jsonpath(expression).find(node)]


def _regex_extract(value: str, transform: dict[str, Any]) -> Any:
    try:
        group = int(transform.get("group", 0))
        match = re.search(str(transform.get("pattern", "")), value)
    except (re.error, TypeError, ValueError):
        return None
    if match is None:
        return None
    try:
        return match.group(group)
    except IndexError:
        return None


def _apply_transforms(value: Any, transforms: list[Any], source_url: str) -> Any:
    for transform in transforms:
        if isinstance(transform, dict):
            if transform.get("type") == "regex_extract" and isinstance(value, str):
                value = _regex_extract(value, transform)
            continue
        if transform == "trim" and isinstance(value, str):
            value = value.strip()
        elif transform == "collapse_whitespace" and isinstance(value, str):
            value = " ".join(value.split())
        elif transform == "lowercase" and isinstance(value, str):
            value = value.lower()
        elif transform == "uppercase" and isinstance(value, str):
            value = value.upper()
        elif transform == "absolute_url" and isinstance(value, str) and value:
            value = urljoin(source_url, value)
        elif transform == "strip_html" and isinstance(value, str):
            value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return value


def _coerce_value(value: str, value_type: str) -> Any:
    if value == "":
        return ""
    if value_type == "integer":
        return int(value.replace(",", ""))
    if value_type == "number":
        return float(value.replace(",", ""))
    if value_type == "boolean":
        normalized = value.casefold()
        if normalized in {"true", "1", "yes", "是"}:
            return True
        if normalized in {"false", "0", "no", "否"}:
            return False
        raise ValueError(f"cannot coerce {value!r} to boolean")
    if value_type == "json":
        return json.loads(value)
    return value


def _missing(value: Any) -> bool:
    return value is None or value == ""


def contract_field_values(html: str, source_url: str, field_specs: dict[str, Any]) -> dict[str, Any]:
    uses_json = any(str(field.get("selector", "")).startswith("jsonpath:") for field in field_specs.values())
    document: Any = json.loads(html) if uses_json else BeautifulSoup(html, "html.parser")
    values: dict[str, Any] = {}
    for key, field in field_specs.items():
        selector = str(field["selector"])
        matches = (
            jsonpath_values(document, selector)
            if selector.startswith("jsonpath:")
            else selector_values(document, selector, source_url)
        )
        if field.get("multipleMatchPolicy") == "error" and len(matches) > 1:
            matches = []
        value = matches[0] if matches else ""
        value = _apply_transforms(value, field.get("transforms", []), source_url)
        if value is None:
            # regex_extract found no match: required fields surface as missing
            # through the normal onError quality gate, optional fields yield null.
            values[key] = None
            continue
        try:
            values[key] = (
                value
                if not isinstance(value, str) and field.get("valueType") == "json"
                else _coerce_value(str(value), str(field.get("valueType", "string")))
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            values[key] = ""
    return values


def discover_from_spec(html: str, base_url: str, list_spec: dict[str, Any]) -> tuple[list[str], str | None]:
    records, next_url = discover_records_from_spec(html, base_url, list_spec)
    return [record["detailUrl"] for record in records], next_url


def discover_records_from_spec(html: str, base_url: str, list_spec: dict[str, Any]) -> tuple[list[dict[str, str]], str | None]:
    item_selector = str(list_spec["itemsSelector"])
    uses_json = item_selector.startswith("jsonpath:")
    document: Any = json.loads(html) if uses_json else BeautifulSoup(html, "html.parser")
    items = jsonpath_values(document, item_selector) if uses_json else document.select(item_selector.removeprefix("css:"))
    records: list[dict[str, str]] = []
    for item in items:
        record: dict[str, Any] = {}
        for key, field in list_spec.get("fields", {}).items():
            selector = str(field["selector"])
            matches = jsonpath_values(item, selector) if selector.startswith("jsonpath:") else selector_values(item, selector, base_url)
            if field.get("multipleMatchPolicy") == "error" and len(matches) > 1:
                matches = []
            value = matches[0] if matches else ""
            record[key] = _apply_transforms(value, field.get("transforms", []), base_url)
        if record.get("detailUrl"):
            records.append(record)

    pagination = list_spec.get("pagination", {})
    if pagination.get("type") != "next_link":
        return records, None
    selector = str(pagination["selector"])
    if selector.startswith("jsonpath:"):
        matches = jsonpath_values(document, selector)
        next_href = str(matches[0]).strip() if matches else ""
    else:
        next_selector = selector.removeprefix("css:").split("::", 1)[0]
        next_anchor = document.select_one(next_selector)
        next_href = str(next_anchor.get("href", "")).strip() if next_anchor else ""
    return records, urljoin(base_url, next_href) if next_href else None


def discover(html: str, base_url: str, profile: dict[str, Any] | None = None) -> tuple[list[str], str | None]:
    profile = profile or detect_profile(html)
    soup = BeautifulSoup(html, "html.parser")
    item_selector = str(profile["listItemsSelector"]).removeprefix("css:")
    detail_urls: list[str] = []
    for item in soup.select(item_selector):
        value = selector_value(item, str(profile["detailLinkSelector"]), base_url)
        if value:
            detail_urls.append(value)
    next_selector = str(profile["paginationSelector"]).removeprefix("css:")
    next_anchor = soup.select_one(next_selector)
    next_href = str(next_anchor.get("href", "")).strip() if next_anchor else ""
    return detail_urls, urljoin(base_url, next_href) if next_href else None


def embedded_list_url(html: str, base_url: str) -> str | None:
    """Return a same-host iframe entrypoint when a source is only a list-page shell."""
    soup = BeautifulSoup(html, "html.parser")
    frames = [*soup.select("iframe#shuju[src]"), *soup.select("iframe[src]")]
    base_host = urlsplit(base_url).hostname
    for frame in frames:
        resolved = urljoin(base_url, str(frame.get("src", "")).strip())
        if resolved and urlsplit(resolved).hostname == base_host:
            return resolved
    return None


def looks_like_dynamic_list_shell(html: str) -> bool:
    """Detect an initially empty list whose page scripts populate it asynchronously."""
    soup = BeautifulSoup(html, "html.parser")
    script_text = " ".join(node.get_text(" ", strip=True) for node in soup.select("script"))
    if not re.search(r"(?:\$\.ajax\s*\(|fetch\s*\(|XMLHttpRequest|axios\.)", script_text):
        return False
    return any(not node.find(True) and not node.get_text(" ", strip=True) for node in soup.select("ul[id], ol[id], tbody[id]"))


def extract_fields(html: str, source_url: str, profile: dict[str, Any] | None = None) -> dict[str, str]:
    profile = profile or DEFAULT_PROFILE
    soup = BeautifulSoup(html, "html.parser")
    values = {key: selector_value(soup, rule[1], source_url) for key, rule in profile["fieldRules"].items()}
    region_selector = str(profile.get("regionSelector", ""))
    values["region"] = selector_value(soup, region_selector, source_url) if region_selector else "未标注"
    values["region"] = values["region"] or "未标注"
    return values


def build_gather_spec(
    collector: dict[str, Any],
    contracts: ContractBundle,
    *,
    mode: str = "list_detail",
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile or DEFAULT_PROFILE
    spec = contracts.gather_template()
    collector_id = collector["id"]
    host = collector["sourceHost"]
    spec["ruleVersionId"] = f"rule_{collector_id}_candidate"
    spec["collectorId"] = collector_id
    spec["collectionVersionRef"]["collectionId"] = collector.get("collectionId", "collection_nationwide_tender")
    spec["sourceRevisionRef"] = {
        "sourceId": f"source_{collector_id}",
        "sourceRevisionId": f"source_revision_{collector_id}_001",
        "configDigest": sha256_digest(collector["sourceUrl"]),
    }
    spec["compiler"]["compiledAt"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    spec["compiler"]["inputDigest"] = sha256_digest(
        {"collectionId": collector.get("collectionId"), "url": collector["sourceUrl"], "intent": collector["intent"]}
    )
    spec["compiler"]["agent"] = {"provider": "local", "model": "crawl4ai-heuristic", "promptVersion": "1.1", "toolchainVersion": "1.0"}
    spec["sourceContext"]["entrypoints"] = [collector["sourceUrl"]]
    spec["sourceContext"]["allowedHosts"] = [host]
    spec["sourceContext"].pop("accessProfileRef", None)
    detail_fields = {
        key: {
            "label": str(label)[:64],
            "selector": selector,
            "valueType": profile.get("fieldValueTypes", {}).get(key, "string"),
            "required": required,
            "onError": "reject_item" if required else "null",
            "multipleMatchPolicy": profile.get("multipleMatchPolicy", "error") if required else "first",
            "transforms": ["trim", "collapse_whitespace"] if key in {"title", "content"} else ["trim"],
            **(
                {"datetimeFormat": "RFC3339", "defaultTimezone": "Asia/Shanghai"}
                if profile.get("fieldValueTypes", {}).get(key) == "datetime"
                else {}
            ),
        }
        for key, (label, selector, required) in profile["fieldRules"].items()
    }
    spec["collect"]["list"] = {
        "request": {"entrypointIndex": 0, "method": "GET", "headers": {"Accept": "text/html,application/xhtml+xml"}, "query": {}},
        "responseType": "html",
        "itemsSelector": profile["listItemsSelector"] if mode == "list_detail" else "css:body",
        "fields": (
            {
                "listTitle": {
                    "label": "列表标题",
                    "selector": profile["listTitleSelector"],
                    "valueType": "string",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "error",
                    "transforms": ["trim", "collapse_whitespace"],
                },
                "listPublishedAt": {
                    "label": "列表日期",
                    "selector": profile["listPublishedAtSelector"],
                    "valueType": "string",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "error",
                    "transforms": ["trim"],
                },
                "detailUrl": {
                    "label": "详情链接",
                    "selector": profile["detailLinkSelector"],
                    "valueType": "url",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "error",
                    "transforms": ["trim", "absolute_url"],
                }
            }
            if mode == "list_detail"
            else detail_fields
        ),
        "pagination": (
            {
                "type": "next_link",
                "selector": profile["paginationSelector"],
                "maxPages": profile["maxPages"],
                "allowCrossHost": False,
            }
            if mode == "list_detail"
            else {"type": "none"}
        ),
    }
    if mode == "list_detail":
        spec["collect"]["detail"] = {
            "request": {"urlTemplate": "{{detailUrl}}", "method": "GET", "headers": {"Accept": "text/html,application/xhtml+xml"}},
            "responseType": "html",
            "fields": detail_fields,
        }
    else:
        spec["collect"].pop("detail", None)
    spec["collect"]["budget"]["maxPages"] = profile["maxPages"] if mode == "list_detail" else 1
    spec["collect"]["budget"]["maxItems"] = profile["maxItems"]
    spec["contract"]["identityFields"] = ["detailUrl"] if mode == "list_detail" else ["title"]
    spec["contract"]["fingerprintFields"] = list(profile["fieldRules"])
    spec["contract"]["normalizedItemSchema"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            key: {"type": "string", **({"minLength": 1} if required else {})}
            for key, (_label, _selector, required) in profile["fieldRules"].items()
        },
        "required": [key for key, (_label, _selector, required) in profile["fieldRules"].items() if required],
        "additionalProperties": False,
    }
    spec["contract"]["outputContractDigest"] = sha256_digest(spec["contract"]["normalizedItemSchema"])
    spec["integrity"]["ruleDigest"] = calculate_rule_digest(spec)
    contracts.validate_gather_spec(spec)
    return spec


def _execution_field(field: dict[str, Any]) -> dict[str, Any]:
    execution = dict(field)
    label = execution.get("label")
    if label is None:
        return execution
    label = str(label).strip()[:64]
    if label:
        execution["label"] = label
    else:
        execution.pop("label", None)
    return execution


def _json_schema_type(value_type: str) -> str | list[str]:
    return {
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "json": ["object", "array", "string", "number", "boolean", "null"],
    }.get(value_type, "string")


def build_gather_spec_from_plan(
    collector: dict[str, Any],
    contracts: ContractBundle,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Compile the constrained LLM RulePlan into a complete deterministic GatherSpec."""
    contracts.validate_rule_plan(plan)
    mode = str(plan["mode"])
    spec = build_gather_spec(collector, contracts, mode=mode)
    list_plan = plan["list"]
    spec["compiler"]["agent"] = {
        "provider": "pending",
        "model": "pending-model",
        "promptVersion": "2.0",
        "toolchainVersion": "2.0",
    }
    spec["sourceContext"]["transport"] = plan["transport"]
    if plan["transport"] == "browser":
        spec["sourceContext"]["browserPolicy"] = {
            "waitUntil": "domcontentloaded",
            "postLoadDelayMs": 3000,
            "pageLoadTimeoutMs": 30000,
            "downloadsEnabled": False,
            "engine": "chromium",
            "engineVersion": "playwright-managed",
            "viewport": {"width": 1440, "height": 900, "deviceScaleFactor": 1},
            "locale": "zh-CN",
            "timezoneId": "Asia/Shanghai",
        }
    else:
        spec["sourceContext"].pop("browserPolicy", None)
    spec["collect"]["list"] = {
        "request": {
            "entrypointIndex": 0,
            "method": "GET",
            "headers": {"Accept": "application/json" if list_plan["responseType"] == "json" else "text/html,application/xhtml+xml"},
            "query": {},
        },
        "responseType": list_plan["responseType"],
        "itemsSelector": list_plan["itemsSelector"],
        "fields": {key: _execution_field(field) for key, field in list_plan["fields"].items()},
        "pagination": dict(list_plan["pagination"]),
    }
    if mode == "list_detail":
        detail_plan = plan["detail"]
        spec["collect"]["detail"] = {
            "request": {
                "urlTemplate": "{{detailUrl}}",
                "method": "GET",
                "headers": {
                    "Accept": "application/json" if detail_plan["responseType"] == "json" else "text/html,application/xhtml+xml"
                },
            },
            "responseType": detail_plan["responseType"],
            "fields": {key: _execution_field(field) for key, field in detail_plan["fields"].items()},
        }
        output_fields = {**list_plan["fields"], **detail_plan["fields"]}
    else:
        spec["collect"].pop("detail", None)
        output_fields = dict(list_plan["fields"])
    pagination = list_plan["pagination"]
    spec["collect"]["budget"]["maxPages"] = int(pagination.get("maxPages", 1))
    spec["collect"]["budget"]["maxItems"] = 10_000
    spec["contract"]["identityFields"] = list(plan["identityFields"])
    spec["contract"]["fingerprintFields"] = list(plan["fingerprintFields"])
    spec["contract"]["fieldBindings"] = dict(plan["bindings"])
    spec["contract"]["normalizedItemSchema"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            key: {
                "type": _json_schema_type(str(field["valueType"])),
                **({"minLength": 1} if field["required"] and _json_schema_type(str(field["valueType"])) == "string" else {}),
            }
            for key, field in output_fields.items()
        },
        "required": [key for key, field in output_fields.items() if field["required"]],
        "additionalProperties": False,
    }
    spec["contract"]["outputContractDigest"] = sha256_digest(spec["contract"]["normalizedItemSchema"])
    spec["integrity"]["ruleDigest"] = calculate_rule_digest(spec)
    contracts.validate_gather_spec(spec)
    return spec


def build_candidate_from_plan(
    collector: dict[str, Any],
    contracts: ContractBundle,
    plan: dict[str, Any],
    list_html: str,
    detail_samples: list[tuple[str, str]],
) -> dict[str, Any]:
    contracts.validate_rule_plan(plan)
    gather_spec = build_gather_spec_from_plan(collector, contracts, plan)
    mode = str(plan["mode"])
    list_spec = gather_spec["collect"]["list"]
    detail_records, _ = discover_records_from_spec(list_html, collector["sourceUrl"], list_spec) if mode == "list_detail" else ([], None)
    output_plan = plan["detail"]["fields"] if mode == "list_detail" else plan["list"]["fields"]
    sample_url, sample_html = detail_samples[0] if detail_samples else (collector["sourceUrl"], list_html)
    values = contract_field_values(sample_html, sample_url, {key: _execution_field(field) for key, field in output_plan.items()})
    soup = BeautifulSoup(sample_html, "html.parser")
    fields = []
    for key, field in output_plan.items():
        sample = values.get(key)
        display_sample = "字段缺失" if _missing(sample) else str(sample)
        if len(display_sample) > 240:
            display_sample = f"{display_sample[:240]}…"
        selector = str(field["selector"])
        evidence = "JSON 字段证据"
        if selector.startswith("css:"):
            evidence_node = soup.select_one(selector.removeprefix("css:").split("::", 1)[0])
            evidence = str(evidence_node)[:500] if evidence_node else "样本中未定位到节点"
        fields.append(
            {
                "key": key,
                "label": field.get("label") or key,
                "selector": selector,
                "required": field["required"],
                "confidence": 0.98 if display_sample != "字段缺失" else 0.35,
                "sample": display_sample,
                "evidence": evidence,
                "warning": None if display_sample != "字段缺失" or field["required"] else "可选字段在当前样本中缺失。",
            }
        )
    detail_url_selector = plan["list"]["fields"].get("detailUrl", {}).get("selector") if mode == "list_detail" else None
    return {
        "id": f"candidate_{hashlib.sha256((collector['sourceUrl'] + stable_json(plan)).encode()).hexdigest()[:16]}",
        "digest": sha256_digest(gather_spec),
        "mode": mode,
        "listSelector": plan["list"]["itemsSelector"],
        "detailLinkSelector": detail_url_selector,
        "pagination": dict(plan["list"]["pagination"]),
        "discovery": {
            "listPagesSampled": 1,
            "detailUrlsDiscovered": len(detail_records),
            "detailPagesValidated": len(detail_samples),
            "detailUrlSamples": [url for url, _html in detail_samples],
        },
        "fields": fields,
        "passedChecks": 18 + sum(display != "字段缺失" for display in (field["sample"] for field in fields)),
        "warningChecks": sum(bool(field["warning"]) for field in fields),
        "gatherSpec": gather_spec,
        "compilerRationale": plan["rationale"],
    }


def build_candidate(
    collector: dict[str, Any],
    contracts: ContractBundle,
    list_html: str,
    detail_samples: list[tuple[str, str]],
) -> dict[str, Any]:
    profile = detect_profile(list_html)
    mode = "list_detail" if discover(list_html, collector["sourceUrl"], profile)[0] else "single"
    sample_url, sample_html = detail_samples[0] if detail_samples else (collector["sourceUrl"], list_html)
    values = extract_fields(sample_html, sample_url, profile)
    fields = []
    for key, (label, selector, required) in profile["fieldRules"].items():
        sample = values.get(key) or "字段缺失"
        if key == "content" and len(sample) > 240:
            sample = f"{sample[:240]}…"
        warning = "部分详情页未披露预算；发布前需要接受风险或排除此字段。" if key == "budget" else None
        evidence_selector = selector.removeprefix("css:").split("::")[0]
        evidence_node = BeautifulSoup(sample_html, "html.parser").select_one(evidence_selector)
        fields.append(
            {
                "key": key,
                "label": label,
                "selector": selector.removesuffix("::text").replace("::attr(datetime)", ""),
                "required": required,
                "confidence": 0.84 if warning else (0.98 if sample != "字段缺失" else 0.4),
                "sample": sample,
                "evidence": str(evidence_node)[:500],
                "warning": warning,
            }
        )
    detail_urls, _ = discover(list_html, collector["sourceUrl"], profile)
    gather_spec = build_gather_spec(collector, contracts, mode=mode, profile=profile)
    return {
        "id": f"candidate_{hashlib.sha256(collector['sourceUrl'].encode()).hexdigest()[:16]}",
        "digest": sha256_digest(gather_spec),
        "mode": mode,
        "listSelector": profile["listItemsSelector"] if mode == "list_detail" else "css:body",
        "detailLinkSelector": profile["detailLinkDisplaySelector"] if mode == "list_detail" else None,
        "pagination": (
            {
                "type": "next_link",
                "selector": profile["paginationSelector"],
                "maxPages": profile["maxPages"],
                "allowCrossHost": False,
            }
            if mode == "list_detail"
            else {"type": "none"}
        ),
        "discovery": {
            "listPagesSampled": 1,
            "detailUrlsDiscovered": len(detail_urls),
            "detailPagesValidated": len(detail_samples),
            "detailUrlSamples": [url for url, _html in detail_samples],
        },
        "fields": fields,
        "passedChecks": 18,
        "warningChecks": sum(bool(field["warning"]) for field in fields),
        "gatherSpec": gather_spec,
    }


def make_item(
    collector: dict[str, Any],
    run: dict[str, Any],
    source_url: str,
    html: str,
    index: int,
    *,
    source_record: dict[str, str] | None = None,
) -> dict[str, Any]:
    gather_spec = collector["candidate"]["gatherSpec"]
    collect = gather_spec["collect"]
    field_specs = collect["detail"]["fields"] if "detail" in collect else collect["list"]["fields"]
    values = contract_field_values(html, source_url, field_specs)
    extracted_data = {**(source_record or {}), **values}
    bindings = gather_spec.get("contract", {}).get("fieldBindings", {})

    def bound_value(role: str) -> Any:
        binding = bindings.get(role)
        if not isinstance(binding, str) or "." not in binding:
            return None
        stage, key = binding.split(".", 1)
        return (source_record or {}).get(key) if stage == "list" else values.get(key)
    list_fields = collect["list"].get("fields", {}) if "detail" in collect else {}
    required_missing = next(
        (
            key
            for key, field in list_fields.items()
            if field.get("required") and _missing((source_record or {}).get(key))
        ),
        None,
    ) or next(
        (key for key, field in field_specs.items() if field.get("required") and _missing(values.get(key))),
        None,
    )
    decision = "rejected" if required_missing else "accepted"
    identity_fields = gather_spec.get("contract", {}).get("identityFields", [])
    identity_payload = {key: extracted_data.get(key) for key in identity_fields if not _missing(extracted_data.get(key))}
    entity_key = hashlib.sha256(stable_json(identity_payload or {"sourceUrl": source_url}).encode()).hexdigest()[:20]
    item_id = f"item_{run['id'].removeprefix('run_')}_{entity_key[:10]}"
    observation_id = f"obs_{run['id'].removeprefix('run_')}_{index:04d}" if decision == "accepted" else None
    observed_at = now_display()
    title = (
        bound_value("title")
        or values.get("title")
        or values.get("projectName")
        or values.get("name")
        or (source_record or {}).get("listTitle")
        or next((value for value in values.values() if isinstance(value, str) and value), None)
        or "未提取标题"
    )
    list_title = bound_value("listTitle") or (source_record or {}).get("listTitle") or title
    return {
        "id": item_id,
        "collectorId": collector["id"],
        "collectorName": collector["name"],
        "sourceHost": collector["sourceHost"],
        "listTitle": list_title,
        "title": title,
        "buyer": values.get("buyer") or values.get("agencyName") or "不适用",
        "region": values.get("region") or "未标注",
        "publishedAt": bound_value("publishedAt") or values.get("publishedAt") or bound_value("listPublishedAt") or "字段缺失",
        "budget": str(values.get("budget") or values.get("amount") or "不适用"),
        "content": (
            bound_value("content")
            or values.get("content")
            or values.get("body")
            or values.get("description")
            or values.get("contentHtml")
            or ""
        ),
        "extractedData": extracted_data,
        "sourceUrl": source_url,
        "decision": decision,
        "changeType": "new" if decision == "accepted" else None,
        "rejectionReason": f"必填字段 {required_missing} 未通过非空质量门" if required_missing else None,
        "entityKey": entity_key,
        "revision": 1 if decision == "accepted" else None,
        "observedAt": observed_at,
        "changeSummary": [],
        "observationHistory": (
            [{"id": observation_id, "runId": run["id"], "observedAt": observed_at, "outcome": "accepted"}] if observation_id else []
        ),
        "lineage": {
            "sourceRevision": collector["candidate"]["gatherSpec"]["sourceRevisionRef"]["sourceRevisionId"],
            "collectionVersion": collector["collectionVersion"],
            "ruleVersion": run["ruleVersion"],
            "runId": run["id"],
            "observationId": observation_id,
            "artifactId": f"artifact_{run['id']}_{index:04d}",
        },
    }


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
