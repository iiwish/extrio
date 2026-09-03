"""Signed evidence-bundle export tests (v0.5).

Covers the build -> verify roundtrip, member layout, SHA256SUMS integrity,
Ed25519 manifest signature, the sink-secret guard, byte-identical
determinism, and since/until + rule-version scope filtering.
"""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.evidence import (
    EvidenceBundleError,
    assert_no_secret_leaks,
    build_evidence_bundle,
    verify_evidence_bundle,
)
from extrio.integrity import (
    LocalEd25519Signer,
    build_rule_attestation,
    immutable_rule_version,
)
from extrio.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXED_GENERATED_AT = "2026-09-03T00:00:00Z"
RUN_OLD_CREATED_AT = "2026-09-01T08:00:00Z"
RUN_NEW_CREATED_AT = "2026-09-02T08:00:00Z"
ITEM_OLD_1_OBSERVED_AT = "2026-09-01T08:30:00Z"
ITEM_OLD_2_OBSERVED_AT = "2026-09-01T09:00:00Z"
ITEM_NEW_1_OBSERVED_AT = "2026-09-02T08:30:00Z"
SINK_URL = "https://hooks.example.com/extrio"
SINK_SECRET = "s3cret-value-123"

EXPECTED_MEMBERS = {
    "manifest.json",
    "manifest.sig",
    "SHA256SUMS",
    "evidence/collector.json",
    "evidence/rules/rule_evidence_demo_v1.json",
    "evidence/rules/attestation_rule_evidence_demo_v1.json",
    "evidence/rules/rule_evidence_demo_v2.json",
    "evidence/rules/attestation_rule_evidence_demo_v2.json",
    "evidence/runs/run_evidence_old.json",
    "evidence/runs/run_evidence_new.json",
    "evidence/items.jsonl",
    "evidence/deliveries.json",
}


def gather_spec() -> dict:
    return {
        "schemaVersion": "extrio.gather.v1",
        "mode": "list_detail",
        "collectionVersion": "tender_notice_v4",
        "sourceRevisionRef": {"sourceRevisionId": "src_evidence_demo"},
        "list": {
            "pagination": "next_link",
            "itemSelector": "css:li.item",
            "fields": {"url": {"selector": "css:a::attr(href)", "kind": "url"}},
        },
        "detail": {"fields": {"title": {"selector": "css:h1::text", "required": True}}},
        "integrity": {},
    }


def publish_rule(
    store: Store,
    collector: dict,
    *,
    rule_version_id: str,
    signer: LocalEd25519Signer,
    contracts: ContractBundle,
) -> tuple[dict, dict]:
    store.ensure_signing_key(signer.trust_record(tenant_id="tenant_demo", revision=1))
    rule_version = immutable_rule_version(
        collector_id=collector["id"],
        spec=gather_spec(),
        rule_version_id=rule_version_id,
    )
    attestation = build_rule_attestation(
        spec=rule_version["gatherSpec"],
        rule_version_id=rule_version_id,
        review_decisions={"title": "approved"},
        signer=signer,
        contracts=contracts,
    )
    rule_version["ruleDigest"] = attestation["ruleDigest"]
    store.publish_rule_bundle(
        collector_id=collector["id"],
        rule_version=rule_version,
        attestation=attestation,
        collector_changes={"status": "published", "activeRuleVersion": rule_version_id},
        audit={"actorId": "user_rule_reviewer_demo", "action": "rule.published", "requestId": "req_evidence_test"},
    )
    return rule_version, attestation


def seed_run(
    store: Store,
    collector: dict,
    *,
    run_id: str,
    rule_version: dict,
    attestation: dict,
    signer: LocalEd25519Signer,
) -> dict:
    run = {
        "id": run_id,
        "operationId": None,
        "collectorId": collector["id"],
        "collectorName": collector["name"],
        "collectionMode": "list_detail",
        "status": "succeeded",
        "startedAt": "2026-09-01T08:00:00Z",
        "duration": "12s",
        "acceptedCount": 2,
        "rejectedCount": 1,
        "pagesFetched": 3,
        "listPagesFetched": 1,
        "detailUrlsDiscovered": 3,
        "detailPagesFetched": 3,
        "recordsOutsideWindow": 0,
        "duplicateDetailUrls": 0,
        "newItems": 2,
        "updatedItems": 0,
        "unchangedItems": 0,
        "paginationStopReason": "next_link_exhausted",
        "ruleVersion": rule_version["id"],
        "ruleDigest": rule_version["ruleDigest"],
        "ruleAttestationId": attestation["attestationId"],
        "signingKeyId": signer.key_id,
        "trustRevision": 1,
        "integrityStatus": "verified",
        "policyContextStatus": "fixed",
        "policyVersion": "policy_evidence_demo_v1",
        "policyDigest": "sha256:" + "3" * 64,
        "executionMode": "initial",
        "windowStart": "2026-08-02",
        "checkpointBefore": None,
        "checkpointAfter": {"policyVersionId": "policy_evidence_demo_v1", "watermark": "2026-09-01T08:00:00Z"},
        "artifactMode": "sampled",
        "summary": "Run finished.",
        "recoveryAction": "无需操作。",
        "items": [],
    }
    store.save_run(run)
    return run


def set_run_created_at(store: Store, run_id: str, created_at: str) -> None:
    with store.transaction() as connection:
        connection.execute("UPDATE runs SET created_at=?, updated_at=? WHERE id=?", (created_at, created_at, run_id))


def make_item(
    item_id: str,
    collector_id: str,
    run_id: str,
    observed_at: str,
    entity_key: str,
    rule_version_id: str,
) -> dict:
    return {
        "id": item_id,
        "collectorId": collector_id,
        "runId": run_id,
        "decision": "accepted",
        "changeType": "new",
        "entityKey": entity_key,
        "revision": 1,
        "extractedData": {"title": f"Tender {entity_key}", "buyer": "示例单位"},
        "sourceUrl": f"https://example.com/detail/{entity_key}",
        "observedAt": observed_at,
        "lineage": {
            "runId": run_id,
            "ruleVersion": rule_version_id,
            "sourceRevision": "src_evidence_demo",
            "collectionVersion": "tender_notice_v4",
            "observationId": f"obs_{entity_key}",
            "artifactId": f"artifact_{entity_key}",
        },
        "observationHistory": [{"id": f"obs_{entity_key}", "runId": run_id, "observedAt": observed_at, "outcome": "accepted"}],
    }


@pytest.fixture
def seeded(tmp_path: Path) -> SimpleNamespace:
    contracts = ContractBundle(ROOT / "docs" / "contracts")
    store = Store(tmp_path / "extrio.db")
    store.initialize()
    collector = store.create_collector("Evidence Demo", "Collect tender notices", "https://example.com/list", "example.com")
    signer = LocalEd25519Signer(tmp_path / "keys" / "evidence-signing-key.pem", "signingkey_evidence_test")
    cipher = CredentialCipher(tmp_path / "keys" / "credential-cipher.key")

    rule_v1, attestation_v1 = publish_rule(store, collector, rule_version_id="rule_evidence_demo_v1", signer=signer, contracts=contracts)
    rule_v2, attestation_v2 = publish_rule(store, collector, rule_version_id="rule_evidence_demo_v2", signer=signer, contracts=contracts)

    seed_run(store, collector, run_id="run_evidence_old", rule_version=rule_v1, attestation=attestation_v1, signer=signer)
    seed_run(store, collector, run_id="run_evidence_new", rule_version=rule_v2, attestation=attestation_v2, signer=signer)
    set_run_created_at(store, "run_evidence_old", RUN_OLD_CREATED_AT)
    set_run_created_at(store, "run_evidence_new", RUN_NEW_CREATED_AT)

    store.save_items(
        "run_evidence_old",
        [
            make_item("item_old_1", collector["id"], "run_evidence_old", ITEM_OLD_1_OBSERVED_AT, "e1", rule_v1["id"]),
            make_item("item_old_2", collector["id"], "run_evidence_old", ITEM_OLD_2_OBSERVED_AT, "e2", rule_v1["id"]),
        ],
    )
    store.save_items(
        "run_evidence_new",
        [make_item("item_new_1", collector["id"], "run_evidence_new", ITEM_NEW_1_OBSERVED_AT, "e3", rule_v2["id"])],
    )

    sink = store.create_sink(collector["id"], cipher=cipher, url=SINK_URL, secret=SINK_SECRET)
    delivery_1 = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_e1")
    store.record_delivery_attempt(delivery_1["id"], status_code=200)
    store.mark_delivery_delivered(delivery_1["id"])
    store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="obs_e2")
    return SimpleNamespace(store=store, collector=collector, signer=signer, cipher=cipher, sink=sink)


def build_bundle(seed: SimpleNamespace, **overrides) -> bytes:
    arguments = {
        "collector_id": seed.collector["id"],
        "signer": seed.signer,
        "cipher": seed.cipher,
        "generated_at": FIXED_GENERATED_AT,
    }
    arguments.update(overrides)
    return build_evidence_bundle(seed.store, **arguments)


def read_members(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def rewrite_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_build_then_verify_roundtrip_is_valid(seeded: SimpleNamespace) -> None:
    bundle = build_bundle(seeded)
    result = verify_evidence_bundle(bundle, seeded.signer.public_key_pem())

    assert result["valid"] is True, result["errors"]
    assert result["errors"] == []

    members = read_members(bundle)
    assert set(members) == EXPECTED_MEMBERS

    manifest = json.loads(members["manifest.json"])
    assert manifest["bundleVersion"] == "extrio.evidence.v1"
    assert manifest["generatedAt"] == FIXED_GENERATED_AT
    assert manifest["collector"] == {
        "id": seeded.collector["id"],
        "name": "Evidence Demo",
        "intent": "Collect tender notices",
        "entryUrl": "https://example.com/list",
    }
    assert manifest["counts"] == {"runs": 2, "items": 3, "deliveries": 2}
    assert result["summary"] == {"runs": 2, "items": 3, "deliveries": 2}
    assert [entry["path"] for entry in manifest["files"]] == sorted(
        path for path in EXPECTED_MEMBERS if path.startswith("evidence/")
    )

    checksum_lines = members["SHA256SUMS"].decode().splitlines()
    checksum_paths = {line.split("  ", 1)[1] for line in checksum_lines}
    assert checksum_paths == EXPECTED_MEMBERS - {"SHA256SUMS", "manifest.sig"}
    for line in checksum_lines:
        digest, path = line.split("  ", 1)
        assert len(digest) == 64
        assert hashlib.sha256(members[path]).hexdigest() == digest

    rule_record = json.loads(members["evidence/rules/rule_evidence_demo_v1.json"])
    assert rule_record["gatherSpec"]["integrity"]["ruleDigest"] == rule_record["ruleDigest"]
    attestation_record = json.loads(members["evidence/rules/attestation_rule_evidence_demo_v1.json"])
    assert attestation_record["ruleVersionId"] == "rule_evidence_demo_v1"
    assert attestation_record["signature"]
    run_record = json.loads(members["evidence/runs/run_evidence_old.json"])
    assert run_record["integrityStatus"] == "verified"
    assert run_record["checkpointAfter"]["watermark"] == "2026-09-01T08:00:00Z"
    item_lines = members["evidence/items.jsonl"].decode().splitlines()
    assert len(item_lines) == 3
    first_item = json.loads(item_lines[0])
    assert set(first_item) == {
        "entityKey",
        "revision",
        "decision",
        "changeType",
        "extractedData",
        "lineage",
        "observationHistory",
        "sourceUrl",
        "observedAt",
        "runId",
    }
    deliveries_record = json.loads(members["evidence/deliveries.json"])
    assert deliveries_record["sinks"][0]["url"] == SINK_URL
    assert {delivery["status"] for delivery in deliveries_record["deliveries"]} == {"delivered", "pending"}
    delivered = next(delivery for delivery in deliveries_record["deliveries"] if delivery["status"] == "delivered")
    assert delivered["sinkUrl"] == SINK_URL
    assert delivered["attempts"][0]["statusCode"] == 200


def test_tampered_item_byte_fails_and_names_the_path(seeded: SimpleNamespace) -> None:
    bundle = build_bundle(seeded)
    members = read_members(bundle)
    items = members["evidence/items.jsonl"]
    members["evidence/items.jsonl"] = items[:-1] + bytes([items[-1] ^ 0x01])
    tampered = rewrite_zip(members)

    result = verify_evidence_bundle(tampered, seeded.signer.public_key_pem())

    assert result["valid"] is False
    assert any("evidence/items.jsonl" in error for error in result["errors"])


def test_manifest_signature_binds_bytes_and_rejects_wrong_key(seeded: SimpleNamespace, tmp_path: Path) -> None:
    bundle = build_bundle(seeded)
    valid = verify_evidence_bundle(bundle, seeded.signer.public_key_pem())
    assert valid["valid"] is True
    manifest_digest = valid["manifestDigest"]
    signature_record = json.loads(read_members(bundle)["manifest.sig"])
    assert signature_record["algorithm"] == "ed25519"
    assert signature_record["signedDigest"] == manifest_digest
    assert signature_record["publicKeyFingerprint"] == valid["publicKeyFingerprint"]

    wrong_signer = LocalEd25519Signer(tmp_path / "keys" / "other-signing-key.pem", "signingkey_other_test")
    wrong = verify_evidence_bundle(bundle, wrong_signer.public_key_pem())
    assert wrong["valid"] is False
    assert any("different key" in error or "signature verification failed" in error for error in wrong["errors"])

    members = read_members(bundle)
    manifest = json.loads(members["manifest.json"])
    manifest["files"][0]["sha256"] = "0" * 64
    members["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    tampered_manifest = verify_evidence_bundle(rewrite_zip(members), seeded.signer.public_key_pem())
    assert tampered_manifest["valid"] is False
    assert any("sha256 mismatch against manifest.json" in error for error in tampered_manifest["errors"])
    assert any("signedDigest" in error for error in tampered_manifest["errors"])


def test_bundle_never_contains_sink_secret_material(seeded: SimpleNamespace) -> None:
    bundle = build_bundle(seeded)
    members = read_members(bundle)

    for data in members.values():
        text = data.decode()
        assert "secretEncrypted" not in text
        assert "secret_encrypted" not in text
        assert SINK_SECRET not in text

    deliveries = json.loads(members["evidence/deliveries.json"])
    assert deliveries["sinks"][0]["url"] == SINK_URL
    assert deliveries["deliveries"][0]["sinkUrl"] == SINK_URL
    assert all("secretConfigured" not in sink for sink in deliveries["sinks"])
    assert verify_evidence_bundle(bundle, seeded.signer.public_key_pem())["valid"] is True

    with pytest.raises(EvidenceBundleError, match="secretEncrypted"):
        assert_no_secret_leaks({"evidence/deliveries.json": '{"secretEncrypted": "gAAAAABm"}'})
    with pytest.raises(EvidenceBundleError, match="decrypted sink secret"):
        assert_no_secret_leaks({"evidence/deliveries.json": f'"url": "{SINK_SECRET}"'}, plaintext_secrets=[SINK_SECRET])
    assert_no_secret_leaks({"evidence/deliveries.json": f'"url": "{SINK_URL}"'}, plaintext_secrets=[SINK_SECRET])


def test_identical_inputs_produce_byte_identical_bundles(seeded: SimpleNamespace) -> None:
    first = build_bundle(seeded)
    second = build_bundle(seeded)
    assert first == second
    assert verify_evidence_bundle(first, seeded.signer.public_key_pem())["valid"] is True

    shifted = build_bundle(seeded, generated_at="2026-09-03T00:00:01Z")
    assert shifted != first


def test_window_filtering_excludes_out_of_window_records(seeded: SimpleNamespace) -> None:
    old_bundle = build_bundle(seeded, until="2026-09-01T23:59:59Z")
    old_result = verify_evidence_bundle(old_bundle, seeded.signer.public_key_pem())
    assert old_result["valid"] is True
    old_members = read_members(old_bundle)
    old_manifest = json.loads(old_members["manifest.json"])
    assert old_manifest["scope"] == {
        "collectorId": seeded.collector["id"],
        "since": None,
        "until": "2026-09-01T23:59:59Z",
        "ruleVersionId": None,
    }
    assert old_manifest["counts"] == {"runs": 1, "items": 2, "deliveries": 0}
    assert "evidence/runs/run_evidence_old.json" in old_members
    assert "evidence/runs/run_evidence_new.json" not in old_members
    old_items = [json.loads(line)["runId"] for line in old_members["evidence/items.jsonl"].decode().splitlines()]
    assert old_items == ["run_evidence_old", "run_evidence_old"]

    new_bundle = build_bundle(seeded, since="2026-09-02T00:00:00Z")
    new_result = verify_evidence_bundle(new_bundle, seeded.signer.public_key_pem())
    assert new_result["valid"] is True
    new_members = read_members(new_bundle)
    new_manifest = json.loads(new_members["manifest.json"])
    assert new_manifest["counts"]["runs"] == 1
    assert new_manifest["counts"]["items"] == 1
    assert "evidence/runs/run_evidence_new.json" in new_members
    assert "evidence/runs/run_evidence_old.json" not in new_members
    new_items = [json.loads(line)["runId"] for line in new_members["evidence/items.jsonl"].decode().splitlines()]
    assert new_items == ["run_evidence_new"]


def test_rule_version_filter_scopes_runs_rules_and_items(seeded: SimpleNamespace) -> None:
    bundle = build_bundle(seeded, rule_version_id="rule_evidence_demo_v2", since="2026-09-02T00:00:00Z")
    result = verify_evidence_bundle(bundle, seeded.signer.public_key_pem())
    assert result["valid"] is True

    members = read_members(bundle)
    manifest = json.loads(members["manifest.json"])
    assert manifest["scope"]["ruleVersionId"] == "rule_evidence_demo_v2"
    assert manifest["counts"]["runs"] == 1
    assert manifest["counts"]["items"] == 1
    assert "evidence/rules/rule_evidence_demo_v2.json" in members
    assert "evidence/rules/attestation_rule_evidence_demo_v2.json" in members
    assert "evidence/rules/rule_evidence_demo_v1.json" not in members
    assert "evidence/runs/run_evidence_old.json" not in members
    run_record = json.loads(members["evidence/runs/run_evidence_new.json"])
    assert run_record["ruleVersion"] == "rule_evidence_demo_v2"


def test_scope_errors_reject_unknown_collector_and_foreign_rule(seeded: SimpleNamespace) -> None:
    with pytest.raises(KeyError):
        build_evidence_bundle(seeded.store, collector_id="collector_missing", signer=seeded.signer)
    with pytest.raises(ValueError, match="does not belong"):
        build_bundle(seeded, rule_version_id="rule_of_another_collector_v9")


def test_unreadable_archive_and_missing_manifest_report_invalid() -> None:
    broken = verify_evidence_bundle(b"not a zip file at all")
    assert broken["valid"] is False
    assert broken["errors"] and "readable" in broken["errors"][0]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("evidence/items.jsonl", "{}\n")
    missing = verify_evidence_bundle(buffer.getvalue())
    assert missing["valid"] is False
    assert any("manifest.json" in error for error in missing["errors"])
