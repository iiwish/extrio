import copy
import json
from pathlib import Path

import pytest

from extrio.contracts import ContractBundle
from extrio.harvest import build_gather_spec
from extrio.integrity import (
    IntegrityError,
    LocalEd25519Signer,
    build_rule_attestation,
    verify_attestation_signature,
    verify_rule_attestation,
)

ROOT = Path(__file__).resolve().parents[2]


def collector() -> dict:
    return {
        "id": "collector_integrity",
        "name": "Integrity",
        "intent": "Collect tenders",
        "sourceUrl": "http://127.0.0.1:8000/demo/tenders",
        "sourceHost": "127.0.0.1",
        "collectionVersion": "tender_notice_v4",
    }


def test_frozen_rule_attestation_example_signature_verifies() -> None:
    attestation = json.loads((ROOT / "docs/contracts/rule-attestation.example.json").read_text())
    public_key = (ROOT / "docs/contracts/rule-attestation.example.public-key.pem").read_text()
    verify_attestation_signature(attestation, public_key)


def test_local_attestation_binds_rule_approval_and_trusted_key(tmp_path: Path) -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    spec = build_gather_spec(collector(), contracts)
    spec["ruleVersionId"] = "rule_v1"
    signer = LocalEd25519Signer(tmp_path / "rule-signing-key.pem", "signingkey_local_test")
    attestation = build_rule_attestation(
        spec=spec,
        rule_version_id="rule_v1",
        review_decisions={"title": "approved", "buyer": "approved"},
        signer=signer,
        contracts=contracts,
    )
    signing_key = signer.trust_record(tenant_id="tenant_demo", revision=1)

    result = verify_rule_attestation(
        spec=spec,
        attestation=attestation,
        signing_key=signing_key,
        contracts=contracts,
        expected_rule_version_id="rule_v1",
        expected_tenant_id="tenant_demo",
    )

    assert result["attestationId"] == attestation["attestationId"]
    assert result["trustRevision"] == 1


def test_tampered_rule_or_attestation_is_rejected_before_runtime(tmp_path: Path) -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    spec = build_gather_spec(collector(), contracts)
    spec["ruleVersionId"] = "rule_v1"
    signer = LocalEd25519Signer(tmp_path / "rule-signing-key.pem", "signingkey_local_test")
    attestation = build_rule_attestation(
        spec=spec,
        rule_version_id="rule_v1",
        review_decisions={"title": "approved"},
        signer=signer,
        contracts=contracts,
    )
    signing_key = signer.trust_record(tenant_id="tenant_demo", revision=1)

    tampered_spec = copy.deepcopy(spec)
    tampered_spec["collect"]["detail"]["fields"]["title"]["selector"] = "css:script::text"
    with pytest.raises(IntegrityError, match="rule digest"):
        verify_rule_attestation(
            spec=tampered_spec,
            attestation=attestation,
            signing_key=signing_key,
            contracts=contracts,
            expected_rule_version_id="rule_v1",
            expected_tenant_id="tenant_demo",
        )

    tampered_attestation = copy.deepcopy(attestation)
    tampered_attestation["approval"]["reviewerSubjectIds"] = ["user_attacker"]
    with pytest.raises(IntegrityError, match="signature"):
        verify_rule_attestation(
            spec=spec,
            attestation=tampered_attestation,
            signing_key=signing_key,
            contracts=contracts,
            expected_rule_version_id="rule_v1",
            expected_tenant_id="tenant_demo",
        )


def test_retired_key_cannot_authorize_a_new_run(tmp_path: Path) -> None:
    contracts = ContractBundle(ROOT / "docs/contracts")
    spec = build_gather_spec(collector(), contracts)
    spec["ruleVersionId"] = "rule_v1"
    signer = LocalEd25519Signer(tmp_path / "rule-signing-key.pem", "signingkey_local_test")
    attestation = build_rule_attestation(
        spec=spec,
        rule_version_id="rule_v1",
        review_decisions={"title": "approved"},
        signer=signer,
        contracts=contracts,
    )
    signing_key = signer.trust_record(tenant_id="tenant_demo", revision=2)
    signing_key["status"] = "retired"

    with pytest.raises(IntegrityError, match="not trusted"):
        verify_rule_attestation(
            spec=spec,
            attestation=attestation,
            signing_key=signing_key,
            contracts=contracts,
            expected_rule_version_id="rule_v1",
            expected_tenant_id="tenant_demo",
        )
