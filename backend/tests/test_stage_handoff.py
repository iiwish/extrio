import copy
from pathlib import Path

import pytest

from extrio.contracts import ContractBundle
from extrio.harvest import build_candidate_from_plan, make_item
from extrio.model_gateway import normalize_discovery_plan, normalize_rule_plan


@pytest.fixture
def staged_candidate(request):
    binding, missing_detail = getattr(request, "param", ("list.detailUrl", False))
    raw = {
        "mode": "list_detail", "transport": "http",
        "list": {"responseType": "html", "itemsSelector": "li", "pagination": {"type": "none"},
                 "fields": {"detailUrl": {"selector": "a::attr(href)", "valueType": "url", "required": True}}},
        "detail": {"responseType": "html", "fields": {
            "detailUrl": {"selector": "meta[name=site]::attr(content)", "valueType": "url", "required": False},
            "content": {"selector": "article::text", "required": False},
        }},
        "bindings": {"detailUrl": binding, "content": "detail.content"},
        "identityFields": ["detailUrl"], "fingerprintFields": ["content"],
    }
    plan = normalize_rule_plan(raw, normalize_discovery_plan(raw))
    collector = {"id": "collector_test", "name": "Test", "intent": "Collect notices", "sourceUrl": "https://example.com/list",
                 "sourceHost": "example.com", "collectionVersion": "notice_v1"}
    detail = '<meta name="site" content="https://example.com"><article>Actual body</article>'
    if missing_detail:
        detail = '<article>Actual body</article>'
    candidate = build_candidate_from_plan(
        collector, ContractBundle(Path(__file__).resolve().parents[2] / "docs/contracts"), plan,
        '<ul><li><a href="/one">One</a></li><li><a href="/two">Two</a></li></ul>',
        [("https://example.com/one", detail)],
    )
    return {**collector, "candidate": candidate}, detail


def test_list_binding_preserves_distinct_detail_urls_and_identity(staged_candidate):
    collector, html = staged_candidate
    items = [make_item(collector, {"id": "run_test", "ruleVersion": "candidate"}, f"https://example.com/{key}", html, i,
                       source_record={"detailUrl": f"https://example.com/{key}"}) for i, key in enumerate(["one", "two"], 1)]
    assert [item["extractedData"]["detailUrl"] for item in items] == ["https://example.com/one", "https://example.com/two"]
    assert len({item["entityKey"] for item in items}) == 2
    assert all(item["content"] == "Actual body" and item["decision"] == "accepted" for item in items)


def test_candidate_evidence_uses_the_bound_stage(staged_candidate):
    collector, _ = staged_candidate
    field = next(field for field in collector["candidate"]["fields"] if field["key"] == "detailUrl")
    assert field["sample"] == "https://example.com/one"
    assert field["selector"] == "css:a::attr(href)"
    assert field["required"] is True


@pytest.mark.parametrize("binding", [None, "detail.detailUrl"])
def test_detail_precedence_remains_without_a_list_binding(staged_candidate, binding):
    collector, html = copy.deepcopy(staged_candidate)
    bindings = collector["candidate"]["gatherSpec"]["contract"]["fieldBindings"]
    bindings.pop("detailUrl")
    if binding:
        bindings["detailUrl"] = binding
    item = make_item(collector, {"id": "run_test", "ruleVersion": "candidate"}, "https://example.com/one", html, 1,
                     source_record={"detailUrl": "https://example.com/one"})
    assert item["extractedData"]["detailUrl"] == "https://example.com"


def test_missing_bound_list_value_does_not_fall_back_to_site_domain(staged_candidate):
    collector, html = staged_candidate
    item = make_item(collector, {"id": "run_test", "ruleVersion": "candidate"}, "https://example.com/one", html, 1,
                     source_record={})
    assert item["extractedData"].get("detailUrl") is None
    assert item["decision"] == "rejected"


@pytest.mark.parametrize("staged_candidate", [("detail.detailUrl", True)], indirect=True)
def test_missing_bound_detail_sample_does_not_display_the_list_value(staged_candidate):
    collector, _ = staged_candidate
    field = next(field for field in collector["candidate"]["fields"] if field["key"] == "detailUrl")
    assert field["sample"] == "字段缺失"
    assert field["warning"] is not None
