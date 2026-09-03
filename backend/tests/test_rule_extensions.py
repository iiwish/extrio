from pathlib import Path

from jsonschema import Draft202012Validator

from extrio.contracts import ContractBundle, SemanticContractError, re2_pattern_error
from extrio.harvest import (
    build_candidate_from_plan,
    build_gather_spec,
    contract_field_values,
    discover_records_from_spec,
    make_item,
)
from extrio.model_gateway import _field_rule, normalize_rule_plan

ROOT = Path(__file__).resolve().parents[2]


def contracts() -> ContractBundle:
    return ContractBundle(ROOT / "docs/contracts")


def field_rule_validator() -> Draft202012Validator:
    defs = contracts().gather_schema["$defs"]
    return Draft202012Validator({"$ref": "#/$defs/fieldRule", "$defs": defs})


def base_field(**overrides) -> dict:
    field = {
        "selector": "css:.notice-budget .amount::text",
        "valueType": "string",
        "required": False,
        "onError": "null",
        "multipleMatchPolicy": "first",
        "transforms": ["trim"],
    }
    field.update(overrides)
    return field


def test_gather_spec_example_validates_against_updated_schema() -> None:
    bundle = contracts()
    bundle.validate_gather_spec(bundle.gather_template())


def test_example_showcases_regex_extract_and_label() -> None:
    template = contracts().gather_template()
    budget = template["collect"]["detail"]["fields"]["budgetAmount"]
    assert {
        "type": "regex_extract",
        "pattern": "[0-9]+(?:\\.[0-9]+)?",
        "group": 0,
    } in budget["transforms"]
    assert budget["label"] == "预算金额（万元）"
    assert template["collect"]["detail"]["fields"]["title"]["label"] == "公告标题"


def test_plain_string_transforms_still_validate_without_label() -> None:
    errors = list(field_rule_validator().iter_errors(base_field()))
    assert errors == []


def test_regex_extract_object_transform_validates() -> None:
    field = base_field(transforms=["trim", {"type": "regex_extract", "pattern": "[0-9]+(\\.[0-9]+)?", "group": 0}])
    assert list(field_rule_validator().iter_errors(field)) == []


def test_regex_extract_object_rejects_bad_group_missing_pattern_and_unknown_type() -> None:
    out_of_range = field_rule_validator().iter_errors(
        base_field(transforms=[{"type": "regex_extract", "pattern": "a", "group": 9}])
    )
    missing_pattern = field_rule_validator().iter_errors(
        base_field(transforms=[{"type": "regex_extract", "group": 1}])
    )
    unknown_type = field_rule_validator().iter_errors(base_field(transforms=[{"type": "split", "pattern": "a"}]))
    assert any(error for error in out_of_range)
    assert any(error for error in missing_pattern)
    assert any(error for error in unknown_type)


def test_field_label_is_optional_and_bounded_to_64_chars() -> None:
    assert list(field_rule_validator().iter_errors(base_field(label="预算金额（万元）"))) == []
    assert list(field_rule_validator().iter_errors(base_field(label="字" * 65)))


def test_rule_plan_field_rule_makes_label_optional_and_accepts_regex_extract() -> None:
    validator = Draft202012Validator({"$ref": "#/$defs/fieldRule", "$defs": contracts().rule_plan_schema["$defs"]})
    without_label = {
        "selector": "css:.amount::text",
        "valueType": "number",
        "required": False,
        "onError": "null",
        "multipleMatchPolicy": "first",
        "transforms": [{"type": "regex_extract", "pattern": "[0-9]+"}],
    }
    assert list(validator.iter_errors(without_label)) == []


def test_re2_pattern_error_rejects_lookahead_lookbehind_backrefs_and_oversize() -> None:
    assert re2_pattern_error("[0-9]+(?:\\.[0-9]+)?") is None
    for pattern in ("(?=预算)[0-9]+", "(?!预算)[0-9]+", "(?<=预算)[0-9]+", "预算(?P<x>[0-9]+)\\1", ""):
        assert re2_pattern_error(pattern) is not None
    assert re2_pattern_error("[0-9]" * 600) == "pattern exceeds the 512-byte limit"


def test_semantic_validator_rejects_non_re2_regex_extract_transform() -> None:
    bundle = contracts()
    spec = {"collect": {"list": {"fields": {"amount": {"transforms": [{"type": "regex_extract", "pattern": "(?i)x"}]}}}}}
    bundle.validate_gather_spec_semantics(spec)
    spec["collect"]["list"]["fields"]["amount"]["transforms"][0]["pattern"] = "(?<=预算)[0-9]+"
    try:
        bundle.validate_gather_spec_semantics(spec)
    except SemanticContractError as exc:
        assert "collect.list.fields.amount" in str(exc)
    else:
        raise AssertionError("non-RE2 pattern must be rejected")


def test_regex_extract_takes_requested_capture_group() -> None:
    values = contract_field_values(
        "<span class=\"amount\">预算金额：355.6万元</span>",
        "https://example.com/detail/1",
        {
            "whole": {
                "selector": "css:.amount::text",
                "valueType": "string",
                "multipleMatchPolicy": "first",
                "transforms": ["trim", {"type": "regex_extract", "pattern": "预算金额：([0-9.]+)万元"}],
            },
            "group1": {
                "selector": "css:.amount::text",
                "valueType": "number",
                "multipleMatchPolicy": "first",
                "transforms": ["trim", {"type": "regex_extract", "pattern": "预算金额：([0-9.]+)万元", "group": 1}],
            },
        },
    )
    assert values == {"whole": "预算金额：355.6万元", "group1": 355.6}


def test_regex_extract_no_match_yields_null_for_optional_fields() -> None:
    values = contract_field_values(
        "<span class=\"amount\">预算金额未披露</span>",
        "https://example.com/detail/1",
        {
            "amount": {
                "selector": "css:.amount::text",
                "valueType": "number",
                "required": False,
                "onError": "null",
                "multipleMatchPolicy": "first",
                "transforms": ["trim", {"type": "regex_extract", "pattern": "[0-9]+(\\.[0-9]+)?"}],
            }
        },
    )
    assert values == {"amount": None}


def test_required_regex_extract_no_match_rejects_the_item() -> None:
    bundle = contracts()
    current = {
        "id": "collector_regex",
        "name": "Regex",
        "intent": "Collect budgets",
        "sourceUrl": "http://127.0.0.1:8000/demo/tenders",
        "sourceHost": "127.0.0.1",
        "collectionVersion": "tender_notice_v4",
    }
    plan = {
        "schemaVersion": "extrio.rule-plan.v1",
        "mode": "list_detail",
        "transport": "http",
        "list": {
            "responseType": "html",
            "itemsSelector": "css:li",
            "fields": {
                "listTitle": {
                    "label": "标题",
                    "selector": "css:a::text",
                    "valueType": "string",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim"],
                },
                "detailUrl": {
                    "selector": "css:a::attr(href)",
                    "valueType": "url",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim", "absolute_url"],
                },
            },
            "pagination": {"type": "none"},
        },
        "detail": {
            "responseType": "html",
            "fields": {
                "budgetAmount": {
                    "label": "预算金额",
                    "selector": "css:.amount::text",
                    "valueType": "number",
                    "required": True,
                    "onError": "reject_item",
                    "multipleMatchPolicy": "first",
                    "transforms": ["trim", {"type": "regex_extract", "pattern": "预算金额：([0-9.]+)万元", "group": 1}],
                }
            },
        },
        "bindings": {"detailUrl": "list.detailUrl", "title": "list.listTitle"},
        "identityFields": ["detailUrl"],
        "fingerprintFields": ["budgetAmount"],
        "rationale": "预算字段使用 regex_extract 提取数字。",
    }
    list_html = '<ul><li><a href="/detail/1">项目 A</a></li></ul>'
    detail_url = "http://127.0.0.1:8000/detail/1"
    candidate = build_candidate_from_plan(
        current,
        bundle,
        plan,
        list_html,
        [(detail_url, '<main><span class="amount">预算金额：355.6万元</span></main>')],
    )
    rejected = make_item(
        {**current, "candidate": candidate},
        {"id": "run_regex_reject", "ruleVersion": "rule_regex_v1"},
        detail_url,
        "<main><span class=\"amount\">预算金额未披露</span></main>",
        1,
        source_record={"listTitle": "项目 A", "detailUrl": detail_url},
    )
    accepted = make_item(
        {**current, "candidate": candidate},
        {"id": "run_regex_accept", "ruleVersion": "rule_regex_v1"},
        detail_url,
        "<main><span class=\"amount\">预算金额：355.6万元</span></main>",
        2,
        source_record={"listTitle": "项目 A", "detailUrl": detail_url},
    )

    assert rejected["decision"] == "rejected"
    assert rejected["extractedData"]["budgetAmount"] is None
    assert accepted["decision"] == "accepted"
    assert accepted["extractedData"]["budgetAmount"] == 355.6


def test_regex_extract_applies_inside_list_discovery() -> None:
    list_spec = {
        "itemsSelector": "css:li",
        "fields": {
            "listTitle": {
                "selector": "css:a::text",
                "multipleMatchPolicy": "first",
                "transforms": ["trim", {"type": "regex_extract", "pattern": "^(.*?)[（(]", "group": 1}],
            },
            "detailUrl": {
                "selector": "css:a::attr(href)",
                "multipleMatchPolicy": "first",
                "transforms": ["trim", "absolute_url"],
            },
        },
        "pagination": {"type": "none"},
    }
    records, _ = discover_records_from_spec(
        '<ul><li><a href="/d/1">项目 A（第一批）</a></li></ul>', "https://example.com/list", list_spec
    )
    assert records == [{"listTitle": "项目 A", "detailUrl": "https://example.com/d/1"}]


def test_profile_compiled_specs_carry_review_labels() -> None:
    bundle = contracts()
    spec = build_gather_spec(
        {
            "id": "collector_labels",
            "name": "Labels",
            "intent": "Collect",
            "sourceUrl": "http://127.0.0.1:8000/demo/tenders",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "tender_notice_v4",
        },
        bundle,
    )
    bundle.validate_gather_spec(spec)
    assert spec["collect"]["detail"]["fields"]["title"]["label"] == "项目名称"
    assert spec["collect"]["list"]["fields"]["detailUrl"]["label"] == "详情链接"


def test_field_rule_passthrough_keeps_label_when_emitted_and_omits_when_absent() -> None:
    labeled = _field_rule("amount", {"selector": ".amount", "label": "预算金额", "transforms": ["trim"]}, "html")
    assert labeled["label"] == "预算金额"

    unlabeled = _field_rule("amount", {"selector": ".amount", "transforms": ["trim"]}, "html")
    assert "label" not in unlabeled


def test_field_rule_normalizes_regex_extract_objects_and_bounds_group() -> None:
    normalized = _field_rule(
        "amount",
        {
            "selector": ".amount",
            "transforms": [
                {"type": "regex_extract", "pattern": "  [0-9.]+ ", "group": 99},
                {"type": "regex_extract", "pattern": "[0-9.]+", "group": 2},
                {"type": "regex_extract"},
            ],
        },
        "html",
    )
    assert normalized["transforms"] == [
        {"type": "regex_extract", "pattern": "[0-9.]+", "group": 8},
        {"type": "regex_extract", "pattern": "[0-9.]+", "group": 2},
    ]


def test_rule_plan_label_passes_through_to_gather_spec_bounded_to_64_chars() -> None:
    bundle = contracts()
    discovery = {
        "mode": "single",
        "transport": "http",
        "list": {
            "responseType": "html",
            "itemsSelector": "css:body",
            "fields": {
                "amount": {
                    "label": "预" * 80,
                    "selector": "css:.amount::text",
                    "valueType": "number",
                    "required": False,
                    "onError": "null",
                    "multipleMatchPolicy": "first",
                    "transforms": [{"type": "regex_extract", "pattern": "[0-9]+(\\.[0-9]+)?"}],
                }
            },
            "pagination": {"type": "none"},
        },
    }
    plan = normalize_rule_plan(
        {
            "identityFields": ["amount"],
            "fingerprintFields": ["amount"],
        },
        discovery,
    )
    spec = build_candidate_from_plan(
        {
            "id": "collector_passthrough",
            "name": "Passthrough",
            "intent": "Collect",
            "sourceUrl": "http://127.0.0.1:8000/demo/tenders",
            "sourceHost": "127.0.0.1",
            "collectionVersion": "tender_notice_v4",
        },
        bundle,
        plan,
        '<main><span class="amount">预算金额：355.6万元</span></main>',
        [],
    )["gatherSpec"]

    bundle.validate_gather_spec(spec)
    field = spec["collect"]["list"]["fields"]["amount"]
    assert field["label"] == "预" * 64
    assert {"type": "regex_extract", "pattern": "[0-9]+(\\.[0-9]+)?"} in field["transforms"]
