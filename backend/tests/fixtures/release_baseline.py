"""Executed with the archived release's imports, never the checkout's Store."""

import json
import sys
from pathlib import Path

from extrio.auth import hash_password
from extrio.config import get_settings
from extrio.contracts import ContractBundle
from extrio.credentials import CredentialCipher
from extrio.harvest import build_gather_spec
from extrio.integrity import LocalEd25519Signer, build_rule_attestation, immutable_rule_version
from extrio.store import Store

settings = get_settings()
store = Store(settings.database_path, database_url=settings.database_url)
store.initialize()
versioned_collections = sys.argv[1].endswith(("-alpha", "-rc"))
rc = sys.argv[1].endswith("-rc")
if sys.argv[1] in {"seed", "seed-alpha", "seed-rc"}:
    collector = store.create_collector("Release history", "Collect public notices", "https://example.test/notices", "example.test")
    signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
    store.ensure_signing_key(signer.trust_record(tenant_id=settings.tenant_id, revision=1))
    contracts = ContractBundle(settings.contracts_path)
    for number in (1, 2):
        spec = build_gather_spec(collector, contracts)
        rule = immutable_rule_version(collector_id=collector["id"], spec=spec, rule_version_id=f"rule_release_{number}")
        attestation = build_rule_attestation(
            spec=rule["gatherSpec"], rule_version_id=rule["id"], review_decisions={"title": "approved"}, signer=signer, contracts=contracts
        )
        store.publish_rule_bundle(
            collector_id=collector["id"],
            rule_version=rule,
            attestation=attestation,
            collector_changes={"activeRuleVersion": rule["id"], "status": "published"},
            audit={"actorId": "user_release", "action": "rule.published", "requestId": f"release_rule_{number}"},
        )
    cipher = CredentialCipher(settings.credential_encryption_key_path)
    store.create_sink(collector["id"], url="https://example.test/hook", secret="release-fixture-secret", cipher=cipher)
    user = store.create_first_auth_user(
        username="release-admin", display_name="Release admin", password_hash=hash_password("Release-fixture-123!")
    )
    store.create_auth_session(token_hash="release-fixture-session", user_id=user["id"], expires_at="2099-01-01T00:00:00Z")
    store.save_run({"id": "run_release", "collectorId": collector["id"], "status": "succeeded", "ruleVersion": "rule_release_2"})
    store.save_items(
        "run_release",
        [
            {
                "id": "item_release",
                "collectorId": collector["id"],
                "runId": "run_release",
                "title": "Historical notice",
                "entityKey": "release_entity",
                "decision": "accepted",
                "observedAt": "2026-09-01T00:00:00Z",
                "lineage": {"runId": "run_release", "ruleVersion": "rule_release_2", "collectionVersion": collector["collectionVersion"]},
            }
        ],
    )
    settings.artifact_path.mkdir(parents=True, exist_ok=True)
    (settings.artifact_path / "historical.html").write_text("<h1>Historical notice</h1>")
    if versioned_collections:
        collection = store.get_collection(collector["collectionId"])
        changed = store.change_collection(collection["id"], collection["revision"], {"fieldDraft": {"fields": [{
            "key": "title", "label": "Title", "description": "", "type": "string",
            "required": True, "identity": True, "fingerprint": True,
        }]}})
        store.publish_collection_version(collection["id"], changed["revision"], user["id"])
        store.create_collector("Frozen source", "Fixed contract", "https://example.test/frozen", "example.test",
                               collection_id=collection["id"], require_existing_collection=True)
        sink = store.list_sinks_for_collector(collector["id"])[0]
        delivery = store.enqueue_delivery(collector_id=collector["id"], sink_id=sink["id"], item_event_id="event_release")
        if rc:
            store.record_delivery_attempt(delivery["id"], status_code=503, error="release-fixture-retry")
            store.save_checkpoint({
                "collectorId": collector["id"], "policyVersionId": collector["collectionPolicy"]["id"],
                "lastSuccessfulRunId": "run_release", "watermark": "2026-09-01T00:00:00Z",
                "advancedAt": "2026-09-01T01:00:00Z",
            })

with store.connect() as connection:
    migrations = sorted(row["id"] for row in connection.execute("SELECT id FROM schema_migrations").fetchall())
    attestations = [
        store.dialect.decode_json(row["data"]) for row in connection.execute("SELECT data FROM rule_attestations ORDER BY id").fetchall()
    ]
collector = next(row for row in store.list_collectors() if row["sourceUrl"] == "https://example.test/notices")
snapshot = {
    "collector": collector,
    "rules": [store.get_rule_version(f"rule_release_{n}") for n in (1, 2)],
    "run": store.get_run("run_release"),
    "items": store.list_items(),
    "attestations": attestations,
    "migrations": migrations,
    "user": store.get_auth_credentials("release-admin"),
    "session": store.get_auth_session("release-fixture-session"),
}
if versioned_collections:
    snapshot.update(
        versions=store.list_collection_versions(collector["collectionId"]),
        boundCollector=next(row for row in store.list_collectors() if row["sourceUrl"] == "https://example.test/frozen"),
        deliveries=store.list_deliveries_for_collector(collector["id"]),
    )
if rc:
    with store.connect() as connection:
        migration_records = [dict(row) for row in connection.execute("SELECT * FROM schema_migrations ORDER BY id").fetchall()]
    snapshot.update(
        migrationRecords=migration_records,
        sinks=store.list_sinks_for_collector(collector["id"]),
        signingKey=store.get_signing_key(settings.signing_key_id),
        auditEvents=store.list_audit_events(),
        checkpoint=store.get_checkpoint(collector["id"]),
        deliveryAttempts=store.list_delivery_attempts(snapshot["deliveries"][0]["id"]),
    )
Path(sys.argv[2]).write_text(json.dumps(snapshot, sort_keys=True, indent=2))
