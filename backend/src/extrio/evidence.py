"""Signed evidence-bundle export (``extrio.evidence.v1``).

An evidence bundle is a deterministic, verifiable ZIP archive that proves what
a collector gathered, under which attested rule, with what lineage. It is pure
library code: the HTTP surface (Wave 2) only streams the returned bytes.

Layout (members are stored sorted by path for byte-identical rebuilds):

* ``manifest.json`` - bundle version, generation time, collector summary,
  scope, per-file SHA-256 list, counts, and the signer's public-key
  fingerprint. The file list covers every evidence file (not ``manifest.json``
  itself, whose digest is signed instead, and not ``manifest.sig``).
* ``manifest.sig`` - Ed25519 signature over the UTF-8 string
  ``sha256:<hex digest of manifest.json>``, plus the signed digest and the
  signer fingerprint. RFC 3161 TSA timestamping is intentionally out of scope
  for v0.5 and remains documented future work.
* ``SHA256SUMS`` - standard ``<sha256>  <path>`` lines for every member except
  itself and ``manifest.sig`` (``manifest.json`` is included).
* ``evidence/collector.json``, ``evidence/rules/rule_<id>.json``,
  ``evidence/rules/attestation_<id>.json``, ``evidence/runs/run_<id>.json``,
  ``evidence/items.jsonl``, and ``evidence/deliveries.json``.

Secrets never enter a bundle: sink records carry URLs only, and a hard guard
scans every serialized evidence file for secret-material markers and decrypted
plaintext before the archive is written.
"""

import base64
import hashlib
import io
import json
import zipfile
from collections.abc import Iterable, Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from extrio.config import get_settings
from extrio.credentials import CredentialCipher
from extrio.integrity import LocalEd25519Signer, utc_now
from extrio.store import EXPORT_ITEMS_CAP, Store

BUNDLE_VERSION = "extrio.evidence.v1"
SIGNATURE_ALGORITHM = "ed25519"
MANIFEST_NAME = "manifest.json"
SIGNATURE_NAME = "manifest.sig"
CHECKSUMS_NAME = "SHA256SUMS"
EVIDENCE_PREFIX = "evidence/"
BUNDLE_DATE_TIME = (1980, 1, 1, 0, 0, 0)
SECRET_MARKERS = ("secretEncrypted", "secret_encrypted")
DELIVERY_VIEW_EXCLUDED_FIELDS = ("secretEncrypted", "secretConfigured")


class EvidenceBundleError(ValueError):
    """Raised when a bundle cannot be built or is structurally unreadable."""

    code = "EVIDENCE_BUNDLE_INVALID"


def public_key_fingerprint(public_key_pem: str) -> str:
    """Return ``sha256:<hex>`` over the DER SubjectPublicKeyInfo of a PEM key."""

    key = serialization.load_pem_public_key(public_key_pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise EvidenceBundleError("bundle signing key is not Ed25519")
    der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return f"sha256:{hashlib.sha256(der).hexdigest()}"


def _default_public_key_pem() -> str:
    """Load the configured signing key's public half (same path as app.py)."""

    settings = get_settings()
    signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
    return signer.public_key_pem()


def _decode_signature(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as exc:
        raise EvidenceBundleError("manifest signature is not valid base64url") from exc


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def assert_no_secret_leaks(files: Mapping[str, str], *, plaintext_secrets: Iterable[str] = ()) -> None:
    """Fail the build when secret material would reach a serialized evidence file."""

    secrets = [secret for secret in plaintext_secrets if secret]
    for path in sorted(files):
        text = files[path]
        for marker in SECRET_MARKERS:
            if marker in text:
                raise EvidenceBundleError(f"evidence file {path} would leak sink secret material ({marker})")
        for secret in secrets:
            if secret in text:
                raise EvidenceBundleError(f"evidence file {path} would leak a decrypted sink secret")


def _delivery_view(delivery: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in delivery.items() if key not in DELIVERY_VIEW_EXCLUDED_FIELDS}


def _zip_bytes(members: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=BUNDLE_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def build_evidence_bundle(
    store: Store,
    *,
    collector_id: str,
    rule_version_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    signer: LocalEd25519Signer,
    cipher: CredentialCipher | None = None,
    generated_at: str | None = None,
) -> bytes:
    """Assemble and sign the evidence bundle for one collector as ZIP bytes.

    ``since``/``until`` are inclusive ISO-8601 bounds filtering runs by their
    ``created_at`` and items by their ``observedAt``. When ``rule_version_id``
    is given the bundle is scoped to runs executed under that rule and ships
    only that rule version; otherwise it covers every rule referenced by the
    in-scope runs. ``generated_at`` defaults to wall-clock time; reproducible
    rebuilds pass a fixed value.
    """

    collector = store.get_collector(collector_id)
    if collector is None:
        raise KeyError(collector_id)

    runs = [
        run
        for run in store.list_runs_for_collector(collector_id, since=since, until=until)
        if rule_version_id is None or run.get("ruleVersion") == rule_version_id
    ]
    scoped_rule_ids = {str(run["ruleVersion"]) for run in runs if run.get("ruleVersion")}
    if rule_version_id is not None:
        scoped_rule_ids.add(rule_version_id)
    collector_rules = {str(version["id"]): version for version in store.list_rule_versions_for_collector(collector_id)}
    rules = [collector_rules[rule_id] for rule_id in sorted(set(collector_rules) & scoped_rule_ids)]
    if rule_version_id is not None and rule_version_id not in {str(rule["id"]) for rule in rules}:
        raise ValueError(f"rule version {rule_version_id} does not belong to collector {collector_id}")

    items = list(store.list_items_for_collector_window(collector_id, since=since, until=until))
    deliveries = [
        delivery
        for delivery in store.list_deliveries_for_collector(collector_id, limit=EXPORT_ITEMS_CAP)
        if (since is None or str(delivery["createdAt"]) >= since) and (until is None or str(delivery["createdAt"]) <= until)
    ]

    sink_views = {str(sink["id"]): sink for sink in store.list_sinks_for_collector(collector_id)}
    plaintext_secrets: list[str] = []
    if cipher is not None:
        for sink_id in sorted(sink_views):
            decrypted = store.get_sink(sink_id, cipher=cipher)
            if decrypted and decrypted.get("secret"):
                plaintext_secrets.append(str(decrypted["secret"]))

    members: dict[str, bytes] = {}
    members[f"{EVIDENCE_PREFIX}collector.json"] = _json_bytes(collector)
    for rule in rules:
        rule_id = str(rule["id"])
        members[f"{EVIDENCE_PREFIX}rules/{rule_id}.json"] = _json_bytes(rule)
        attestation = rule.get("attestation")
        if attestation is not None:
            members[f"{EVIDENCE_PREFIX}rules/attestation_{rule_id}.json"] = _json_bytes(attestation)
    for run in runs:
        members[f"{EVIDENCE_PREFIX}runs/{run['id']}.json"] = _json_bytes(run)
    members[f"{EVIDENCE_PREFIX}items.jsonl"] = "".join(
        json.dumps(
            {
                "entityKey": item.get("entityKey"),
                "revision": item.get("revision"),
                "decision": item.get("decision"),
                "changeType": item.get("changeType"),
                "extractedData": item.get("extractedData"),
                "lineage": item.get("lineage"),
                "observationHistory": item.get("observationHistory"),
                "sourceUrl": item.get("sourceUrl"),
                "observedAt": item.get("observedAt"),
                "runId": item.get("runId"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for item in items
    ).encode()
    members[f"{EVIDENCE_PREFIX}deliveries.json"] = _json_bytes(
        {
            "deliveries": [
                {
                    **_delivery_view(delivery),
                    "sinkType": sink_views.get(str(delivery["sinkId"]), {}).get("type"),
                    "sinkUrl": sink_views.get(str(delivery["sinkId"]), {}).get("url"),
                    "attempts": store.list_delivery_attempts(str(delivery["id"])),
                }
                for delivery in deliveries
            ],
            "sinks": [
                {
                    "id": sink["id"],
                    "type": sink["type"],
                    "url": sink["url"],
                    "enabled": bool(sink["enabled"]),
                    "version": int(sink["version"]),
                    "createdAt": sink["createdAt"],
                    "updatedAt": sink["updatedAt"],
                }
                for sink in (sink_views[sink_id] for sink_id in sorted(sink_views))
            ],
        }
    )

    serialized = {path: data.decode() for path, data in members.items()}
    assert_no_secret_leaks(serialized, plaintext_secrets=plaintext_secrets)

    public_pem = signer.public_key_pem()
    fingerprint = public_key_fingerprint(public_pem)
    file_entries = [
        {"path": path, "sha256": hashlib.sha256(members[path]).hexdigest(), "bytes": len(members[path])}
        for path in sorted(members)
    ]
    manifest = {
        "bundleVersion": BUNDLE_VERSION,
        "generatedAt": generated_at or utc_now(),
        "collector": {
            "id": collector["id"],
            "name": collector.get("name"),
            "intent": collector.get("intent"),
            "entryUrl": collector.get("sourceUrl"),
        },
        "scope": {"collectorId": collector_id, "since": since, "until": until, "ruleVersionId": rule_version_id},
        "counts": {"runs": len(runs), "items": len(items), "deliveries": len(deliveries)},
        "signer": {"keyId": signer.key_id, "algorithm": SIGNATURE_ALGORITHM, "publicKeyFingerprint": fingerprint},
        "files": file_entries,
    }
    manifest_bytes = _json_bytes(manifest)
    members[MANIFEST_NAME] = manifest_bytes

    signed_digest = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    members[SIGNATURE_NAME] = _json_bytes(
        {
            "algorithm": SIGNATURE_ALGORITHM,
            "publicKeyFingerprint": fingerprint,
            "signature": signer.sign(signed_digest.encode()),
            "signedDigest": signed_digest,
        }
    )

    checksums = "".join(
        f"{hashlib.sha256(members[path]).hexdigest()}  {path}\n" for path in sorted(members) if path not in {CHECKSUMS_NAME, SIGNATURE_NAME}
    )
    members[CHECKSUMS_NAME] = checksums.encode()
    return _zip_bytes(members)


def _parse_checksums(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, separator, path = line.partition("  ")
        if not separator or len(digest) != 64 or not path:
            raise EvidenceBundleError(f"SHA256SUMS line is malformed: {line!r}")
        entries[path] = digest.lower()
    return entries


def verify_evidence_bundle(zip_bytes: bytes, public_key_pem: str | None = None) -> dict[str, Any]:
    """Verify a bundle's file hashes, checksum list, and Ed25519 manifest signature.

    Returns ``{"valid": bool, "errors": [...], "summary": counts}``. Any single
    tampered byte surfaces as an error naming the offending path. When
    ``public_key_pem`` is omitted the configured signing key (the same key the
    rule attestations use) provides the public half.
    """

    result: dict[str, Any] = {"valid": False, "errors": [], "summary": {"runs": 0, "items": 0, "deliveries": 0}}
    errors: list[str] = result["errors"]
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        errors.append(f"archive is not a readable evidence bundle: {exc}")
        return result

    if MANIFEST_NAME not in members or SIGNATURE_NAME not in members:
        errors.append(f"bundle is missing {MANIFEST_NAME} or {SIGNATURE_NAME}")
        return result
    try:
        manifest = json.loads(members[MANIFEST_NAME])
        signature_record = json.loads(members[SIGNATURE_NAME])
    except ValueError as exc:
        errors.append(f"{MANIFEST_NAME} or {SIGNATURE_NAME} is not valid JSON: {exc}")
        return result
    if not isinstance(manifest, dict) or not isinstance(signature_record, dict):
        errors.append(f"{MANIFEST_NAME} or {SIGNATURE_NAME} is not a JSON object")
        return result
    result["summary"] = dict(manifest.get("counts") or {})

    listed_files = manifest.get("files")
    if not isinstance(listed_files, list):
        errors.append(f"{MANIFEST_NAME} file list is missing")
        return result

    protected = {MANIFEST_NAME, SIGNATURE_NAME, CHECKSUMS_NAME}
    for entry in listed_files:
        if not isinstance(entry, dict) or "path" not in entry:
            errors.append(f"{MANIFEST_NAME} contains a malformed file entry: {entry!r}")
            continue
        path = str(entry["path"])
        if path not in members:
            errors.append(f"{path}: listed in manifest but missing from the bundle")
            continue
        digest = hashlib.sha256(members[path]).hexdigest()
        if entry.get("sha256") != digest or entry.get("bytes") != len(members[path]):
            errors.append(f"{path}: sha256 mismatch against {MANIFEST_NAME}")

    listed_paths = {str(entry.get("path")) for entry in listed_files if isinstance(entry, dict)}
    for path in sorted(members):
        if path not in listed_paths and path not in protected:
            errors.append(f"unexpected file in bundle: {path}")

    if CHECKSUMS_NAME not in members:
        errors.append(f"bundle is missing {CHECKSUMS_NAME}")
    else:
        try:
            checksum_entries = _parse_checksums(members[CHECKSUMS_NAME].decode())
        except (UnicodeDecodeError, EvidenceBundleError) as exc:
            errors.append(f"{CHECKSUMS_NAME} is unreadable: {exc}")
        else:
            expected_paths = {path for path in members if path not in {CHECKSUMS_NAME, SIGNATURE_NAME}}
            for path in sorted(expected_paths):
                recorded = checksum_entries.get(path)
                digest = hashlib.sha256(members[path]).hexdigest()
                if recorded is None:
                    errors.append(f"{CHECKSUMS_NAME} has no entry for {path}")
                elif recorded != digest:
                    errors.append(f"{path}: sha256 mismatch against {CHECKSUMS_NAME}")
            for path in sorted(set(checksum_entries) - expected_paths):
                errors.append(f"{CHECKSUMS_NAME} lists unknown path {path}")

    pem = public_key_pem if public_key_pem is not None else _default_public_key_pem()
    try:
        fingerprint = public_key_fingerprint(pem)
    except EvidenceBundleError as exc:
        errors.append(str(exc))
        return result
    result["publicKeyFingerprint"] = fingerprint
    result["manifestDigest"] = f"sha256:{hashlib.sha256(members[MANIFEST_NAME]).hexdigest()}"

    signed_digest = str(signature_record.get("signedDigest", ""))
    if signed_digest != result["manifestDigest"]:
        errors.append(f"{MANIFEST_NAME} digest does not match {SIGNATURE_NAME} signedDigest")
    record_fingerprint = signature_record.get("publicKeyFingerprint")
    if record_fingerprint != fingerprint:
        errors.append(f"{SIGNATURE_NAME} was signed by a different key ({record_fingerprint})")
    manifest_fingerprint = (manifest.get("signer") or {}).get("publicKeyFingerprint")
    if manifest_fingerprint != fingerprint:
        errors.append(f"{MANIFEST_NAME} signer fingerprint does not match the verification key")
    if signature_record.get("algorithm") != SIGNATURE_ALGORITHM:
        errors.append(f"{SIGNATURE_NAME} algorithm is not {SIGNATURE_ALGORITHM}")
    try:
        key = serialization.load_pem_public_key(pem.encode())
        if not isinstance(key, Ed25519PublicKey):
            raise EvidenceBundleError("verification key is not Ed25519")
        key.verify(_decode_signature(str(signature_record.get("signature", ""))), signed_digest.encode())
    except (InvalidSignature, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, EvidenceBundleError):
            errors.append(str(exc))
        else:
            errors.append("manifest signature verification failed against the provided public key")

    result["valid"] = not errors
    return result
