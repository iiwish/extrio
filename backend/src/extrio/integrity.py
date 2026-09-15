import base64
import copy
import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from jsonschema import ValidationError

from extrio.contracts import ContractBundle

ATTESTATION_DOMAIN = b"extrio.rule-attestation.v1\n"


class IntegrityError(ValueError):
    def __init__(self, message: str, code: str = "RULE_ATTESTATION_INVALID"):
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, UnicodeError, TypeError, ValueError) as exc:
        raise IntegrityError("payload is not valid RFC 8785 JSON", "CANONICALIZATION_FAILED") from exc


def digest_value(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def calculate_rule_digest(spec: dict[str, Any]) -> str:
    return digest_value({key: value for key, value in spec.items() if key != "integrity"})


def finalize_rule_spec(spec: dict[str, Any], rule_version_id: str) -> str:
    spec["ruleVersionId"] = rule_version_id
    rule_digest = calculate_rule_digest(spec)
    spec["integrity"]["ruleDigest"] = rule_digest
    return rule_digest


def attestation_signing_bytes(attestation: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in attestation.items() if key != "signature"}
    return ATTESTATION_DOMAIN + canonical_bytes(payload)


def _decode_signature(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as exc:
        raise IntegrityError("rule attestation signature is not valid base64url") from exc


def verify_attestation_signature(attestation: dict[str, Any], public_key_pem: str) -> None:
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        if not isinstance(public_key, Ed25519PublicKey):
            raise IntegrityError("signing key is not Ed25519")
        public_key.verify(_decode_signature(str(attestation["signature"])), attestation_signing_bytes(attestation))
    except (InvalidSignature, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError("rule attestation signature verification failed") from exc


class LocalEd25519Signer:
    """Development-only file signer. Production replaces this with KMS/HSM RPC."""

    def __init__(self, private_key_path: Path, key_id: str):
        self.private_key_path = private_key_path
        self.key_id = key_id
        self._private_key: Ed25519PrivateKey | None = None

    def _load_or_create(self) -> Ed25519PrivateKey:
        if self.private_key_path.is_symlink() or (self.private_key_path.exists() and not self.private_key_path.is_file()):
            raise IntegrityError("signing key must be a regular file")
        if self.private_key_path.exists() and self.private_key_path.stat().st_mode & 0o077:
            raise IntegrityError("signing key permissions must exclude group and other users")
        if self._private_key is not None:
            if not self.private_key_path.exists():
                raise IntegrityError("signing key file is missing")
        self.private_key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = self.private_key_path.read_bytes()
        except FileNotFoundError:
            private_key = Ed25519PrivateKey.generate()
            payload = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            try:
                descriptor = os.open(self.private_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                payload = self.private_key_path.read_bytes()
            else:
                with os.fdopen(descriptor, "wb") as key_file:
                    key_file.write(payload)
        loaded = serialization.load_pem_private_key(payload, password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise IntegrityError("configured signing key is not Ed25519")
        self._private_key = loaded
        return loaded

    def sign(self, payload: bytes) -> str:
        signature = self._load_or_create().sign(payload)
        return base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    def validate_registered_identity(self, store) -> None:
        trust = store.get_signing_key(self.key_id)
        if trust:
            if not self.private_key_path.is_file():
                raise IntegrityError("registered signing key file is missing; restore the original material")
            if self.public_key_pem() != trust["publicKeyPem"]:
                raise IntegrityError("signing key identity does not match the registered key")
            if trust["status"] != "trusted":
                raise IntegrityError("configured signing key is not trusted")

    def public_key_pem(self) -> str:
        return (
            self._load_or_create()
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    def trust_record(self, *, tenant_id: str, revision: int) -> dict[str, Any]:
        self._load_or_create()
        trusted_at = datetime.fromtimestamp(self.private_key_path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")
        return {
            "id": self.key_id,
            "tenantId": tenant_id,
            "status": "trusted",
            "algorithm": "Ed25519",
            "publicKeyPem": self.public_key_pem(),
            "revision": revision,
            "trustedAt": trusted_at,
        }


def build_rule_attestation(
    *,
    spec: dict[str, Any],
    rule_version_id: str,
    review_decisions: dict[str, str],
    signer: LocalEd25519Signer,
    contracts: ContractBundle,
    tenant_id: str = "tenant_demo",
    reviewer_subject_id: str = "user_local_operator",
) -> dict[str, Any]:
    signed_at = utc_now()
    rule_digest = finalize_rule_spec(spec, rule_version_id)
    approval = {
        "decisionId": f"approval_{uuid.uuid4().hex}",
        "decision": "approved",
        "submitterSubjectId": reviewer_subject_id,
        "reviewerSubjectIds": [reviewer_subject_id],
        "approvedAt": signed_at,
        "reviewPolicyDigest": digest_value({"policy": "manual_rule_review_v1", "requiredRoles": ["RuleReviewer"], "minimumReviewers": 1}),
        "evidenceDigest": digest_value({"reviewDecisions": review_decisions, "ruleDigest": rule_digest}),
    }
    attestation = {
        "schemaVersion": "extrio.rule-attestation.v1",
        "attestationId": f"attestation_{uuid.uuid4().hex}",
        "tenantId": tenant_id,
        "ruleVersionId": rule_version_id,
        "ruleDigest": rule_digest,
        "approval": approval,
        "purpose": "extrio-rule-publish-v1",
        "keyId": signer.key_id,
        "algorithm": "Ed25519",
        "signedAt": signed_at,
        "signature": "",
    }
    attestation["signature"] = signer.sign(attestation_signing_bytes(attestation))
    contracts.validate_rule_attestation(attestation)
    return attestation


def verify_rule_attestation(
    *,
    spec: dict[str, Any],
    attestation: dict[str, Any],
    signing_key: dict[str, Any],
    contracts: ContractBundle,
    expected_rule_version_id: str,
    expected_tenant_id: str,
) -> dict[str, Any]:
    try:
        contracts.validate_gather_spec(spec)
        contracts.validate_rule_attestation(attestation)
    except ValidationError as exc:
        raise IntegrityError(f"rule integrity schema validation failed: {exc.message}") from exc

    calculated_digest = calculate_rule_digest(spec)
    if spec["integrity"]["ruleDigest"] != calculated_digest:
        raise IntegrityError("GatherSpec rule digest does not match its canonical payload")
    if attestation["ruleDigest"] != calculated_digest:
        raise IntegrityError("attested rule digest does not match GatherSpec rule digest")
    if spec["ruleVersionId"] != expected_rule_version_id or attestation["ruleVersionId"] != expected_rule_version_id:
        raise IntegrityError("rule version binding does not match the fixed Run context")
    if attestation["tenantId"] != expected_tenant_id or signing_key["tenantId"] != expected_tenant_id:
        raise IntegrityError("tenant binding does not match the fixed Run context")
    if signing_key["id"] != attestation["keyId"] or signing_key.get("algorithm") != "Ed25519":
        raise IntegrityError("signing key binding is invalid")
    if signing_key.get("status") != "trusted":
        raise IntegrityError("signing key is not trusted for new Runs")
    if "expiresAt" in attestation:
        expires_at = datetime.fromisoformat(attestation["expiresAt"].replace("Z", "+00:00"))
        if expires_at <= datetime.now(UTC):
            raise IntegrityError("rule attestation is expired")

    verify_attestation_signature(attestation, signing_key["publicKeyPem"])
    return {
        "attestationId": attestation["attestationId"],
        "ruleDigest": calculated_digest,
        "keyId": signing_key["id"],
        "trustRevision": int(signing_key["revision"]),
    }


def immutable_rule_version(
    *, collector_id: str, spec: dict[str, Any], rule_version_id: str, tenant_id: str = "tenant_demo"
) -> dict[str, Any]:
    frozen_spec = copy.deepcopy(spec)
    rule_digest = finalize_rule_spec(frozen_spec, rule_version_id)
    return {
        "id": rule_version_id,
        "tenantId": tenant_id,
        "collectorId": collector_id,
        "ruleDigest": rule_digest,
        "gatherSpec": frozen_spec,
        "status": "published",
        "createdAt": utc_now(),
    }
