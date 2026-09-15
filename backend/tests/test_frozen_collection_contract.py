import copy

import pytest

import extrio.app as app_module
from extrio.collection_fields import build_collection_version_contract, project_source_contract
from extrio.harvest import build_candidate_from_plan, make_item
from extrio.model_gateway import normalize_discovery_plan, normalize_rule_plan
from extrio.store import Store


def field(key="title", **changes):
    return {
        "key": key,
        "label": key,
        "description": "",
        "type": "string",
        "required": True,
        "identity": True,
        "fingerprint": True,
        **changes,
    }


def version(fields=None):
    return {
        **build_collection_version_contract(fields or [field()]),
        "id": "colver_test_v1",
        "collectionId": "collection_test",
        "versionNumber": 1,
    }


def candidate(frozen=None):
    collector = {
        "id": "collector_test",
        "name": "Test",
        "intent": "Title",
        "sourceHost": "example.com",
        "sourceUrl": "https://example.com/a",
        "collectionId": "collection_test",
        "collectionVersion": "colver_test_v1",
        "frozenCollectionVersion": frozen or version(),
    }
    raw = {
        "mode": "single",
        "transport": "http",
        "list": {
            "responseType": "html",
            "itemsSelector": "css:body",
            "pagination": {"type": "none"},
            "fields": {"title": {"selector": "css:h1::text", "required": False}, "extra": {"selector": "css:p::text", "required": True}},
        },
        "identityFields": ["extra"],
        "fingerprintFields": ["extra"],
        "rationale": "test",
    }
    plan = normalize_rule_plan(raw, normalize_discovery_plan(raw))
    result = build_candidate_from_plan(collector, app_module.contracts, plan, "<h1>A</h1><p>B</p>", [])
    return {**collector, "candidate": result}


def test_compiler_cannot_override_frozen_schema_or_identity():
    collector = candidate()
    spec = collector["candidate"]["gatherSpec"]
    assert spec["collectionVersionRef"] == {"collectionId": "collection_test", "collectionVersionId": "colver_test_v1", "version": "1"}
    for key in ("normalizedItemSchema", "identityFields", "fingerprintFields", "outputContractDigest"):
        assert spec["contract"][key] == version()[key]
    assert spec["collect"]["list"]["fields"]["title"]["required"] is True
    assert {f["key"] for f in collector["candidate"]["fields"]} == {"title"}
    item = make_item(collector, {"id": "run_test", "ruleVersion": "rule_test"}, collector["sourceUrl"], "<h1>A</h1><p>B</p>", 1)
    assert item["extractedData"] == {"title": "A"}
    assert item["decision"] == "accepted"


def test_single_page_review_sample_matches_actual_extraction():
    collector = candidate()
    item = make_item(collector, {"id": "run_sample", "ruleVersion": "rule_sample"}, collector["sourceUrl"], "<h1>A</h1><p>B</p>", 1)
    title = collector["candidate"]["fields"][0]
    assert title["sample"] == item["extractedData"]["title"] == "A"
    assert title["confidence"] == 0.98


@pytest.mark.parametrize("kind", ["string", "number", "integer", "boolean", "date", "datetime", "url", "html", "object", "array"])
@pytest.mark.parametrize("published", [False, True])
def test_frozen_source_projection_preserves_semantic_type(kind, published):
    frozen = version([field(type=kind)])
    collector = candidate(frozen)
    rule = collector["candidate"] if published else None
    if published:
        collector = {**collector, "activeRuleVersion": "rule_frozen"}
    projected = project_source_contract(collector, rule)
    assert projected["fields"][0]["type"] == kind


def test_frozen_required_field_missing_from_model_is_compile_error():
    with pytest.raises(ValueError, match="missing"):
        candidate(version([field("notOnPage")]))


def test_runtime_rejects_values_outside_frozen_field_type():
    collector = candidate(version([field(type="number")]))
    # Simulate malformed execution output without changing the frozen schema.
    collector["candidate"]["gatherSpec"]["collect"]["list"]["fields"]["title"]["valueType"] = "string"
    item = make_item(collector, {"id": "run_test", "ruleVersion": "rule_test"}, collector["sourceUrl"], "<h1>not a number</h1><p>B</p>", 1)
    assert item["decision"] == "rejected"
    assert "合同" in item["rejectionReason"]


def test_bound_version_resolution_never_reads_latest_or_draft(tmp_path):
    store = Store(tmp_path / "frozen.db")
    store.initialize()
    collector = store.create_collector("Old", "Old", "https://example.com/a", "example.com")
    collection = store.get_collection(collector["collectionId"])
    store.collection_command(
        "PATCH", collection["id"], {"revision": collection["revision"], "fieldDraft": {"fields": [field()]}}, "draft-key", audit=None
    )
    latest = store.publish_collection_version(collection["id"], collection["revision"] + 1, "test")
    assert store.collector_compilation_context(collector).get("frozenCollectionVersion") is None
    bound = {**collector, "collectionVersion": latest["id"]}
    assert store.collector_compilation_context(bound)["expectedFields"] == latest["fields"]
    with pytest.raises(ValueError, match="VERSION_NOT_FOUND"):
        store.collector_compilation_context({**bound, "collectionVersion": "colver_missing"})
    other = copy.deepcopy(bound)
    other["collectionId"] = "another_collection"
    with pytest.raises(ValueError, match="VERSION_NOT_FOUND"):
        store.collector_compilation_context(other)


@pytest.mark.parametrize("fields", [[field(identity=False)], [field(fingerprint=False)], [field(f"key{i}") for i in range(17)]])
def test_publish_rejects_unexecutable_contract(fields):
    with pytest.raises(ValueError):
        build_collection_version_contract(fields)


def test_contract_digest_covers_identity_and_fingerprint_semantics():
    fields = [field(), field("code", identity=False, fingerprint=False)]
    base = version(fields)
    changed = version([field(identity=False), field("code", fingerprint=False)])
    assert base["normalizedItemSchema"] == changed["normalizedItemSchema"]
    assert base["outputContractDigest"] != changed["outputContractDigest"]


@pytest.mark.parametrize("value_type", ["number", "integer", "boolean", "date", "datetime", "url", "object", "array"])
def test_missing_optional_typed_output_is_null_not_a_rejected_item(value_type):
    collector = candidate(version([field(), field("extra", type=value_type, required=False, identity=False)]))
    item = make_item(collector, {"id": "run_test", "ruleVersion": "rule_test"}, collector["sourceUrl"], "<h1>A</h1>", 1)
    assert item["decision"] == "accepted"
    assert item["extractedData"]["extra"] is None


def test_repair_preserves_frozen_contract_digest_and_version_ref():
    from extrio.explorer import _apply_repair_contract

    old = candidate()["candidate"]["gatherSpec"]
    repaired = copy.deepcopy(candidate()["candidate"])
    repaired["gatherSpec"]["collectionVersionRef"]["collectionVersionId"] = "colver_wrong"
    _apply_repair_contract(repaired, old)
    assert repaired["gatherSpec"]["contract"] == old["contract"]
    assert repaired["gatherSpec"]["collectionVersionRef"] == old["collectionVersionRef"]
