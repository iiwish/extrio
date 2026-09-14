"""Offline key operations for the supported single-host deployment."""

import argparse
import json
import re
import sys
from pathlib import Path

from extrio.cli import _assert_stopped, _validate_keys
from extrio.config import get_settings
from extrio.credentials import CredentialCipher, validate_stored_credentials
from extrio.instance_guard import instance_lock
from extrio.integrity import LocalEd25519Signer
from extrio.store import Store, utc_now


def initialize_keys(settings, store, *, offline=False):
    if not offline:
        raise RuntimeError("key initialization requires --offline")
    with instance_lock(settings.artifact_path, exclusive=True):
        store.initialize()
        _assert_stopped(store)
        cipher = CredentialCipher(settings.credential_encryption_key_path)
        validate_stored_credentials(store, cipher)
        signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
        signer.validate_registered_identity(store)
        cipher._keys(create=True)
        store.ensure_signing_key(
            signer.trust_record(tenant_id=settings.tenant_id, revision=1),
            audit={"actorId": "local_operator", "action": "signing_key.created", "requestId": "offline_key_initialization"},
        )
        settings.artifact_path.mkdir(parents=True, exist_ok=True)
        return {"signingKeyId": settings.signing_key_id, "initialized": True}


def rotate_credentials(settings, store, *, offline=False):
    if not offline:
        raise RuntimeError("credential rotation requires --offline and stopped instance processes")
    with instance_lock(settings.artifact_path, exclusive=True):
        _assert_stopped(store)
        _validate_keys(settings, store)
        cipher = CredentialCipher(settings.credential_encryption_key_path)
        result = cipher.rotate()
        count = 0
        # The additive keyring is committed first. A failed database transaction
        # leaves both generations decryptable rather than stranding credentials.
        with store.transaction() as connection:
            rows = connection.execute("SELECT id, secret_encrypted FROM sinks WHERE secret_encrypted IS NOT NULL").fetchall()
            for row in rows:
                token = cipher.encrypt(cipher.decrypt(row["secret_encrypted"]))
                connection.execute("UPDATE sinks SET secret_encrypted=? WHERE id=?", (token, row["id"]))
                count += 1
            row = connection.execute("SELECT data FROM platform_settings WHERE key='model-provider-credentials'").fetchone()
            if row:
                payload = store.dialect.decode_json(row["data"])
                payload["credentials"] = {
                    key: cipher.encrypt(cipher.decrypt(token)) for key, token in payload.get("credentials", {}).items()
                }
                count += len(payload["credentials"])
                connection.execute(
                    "UPDATE platform_settings SET data=?, updated_at=? WHERE key='model-provider-credentials'",
                    (store.dialect.json_param(payload), utc_now()),
                )
            store._append_audit_event(
                connection,
                tenant_id=settings.tenant_id,
                target_type="Instance",
                target_id=settings.tenant_id,
                audit={
                    "actorId": "local_operator",
                    "action": "credentials.rotated",
                    "requestId": "offline_key_rotation",
                    "details": {"reencryptedCredentials": count},
                },
                before_digest=None,
                after_digest=None,
            )
        return {**result, "reencryptedCredentials": count}


def create_signing_key(settings, store, key_id: str, path: Path, *, offline=False):
    if not offline:
        raise RuntimeError("signing key creation requires --offline")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,127}", key_id):
        raise ValueError("invalid signing key ID")
    with instance_lock(settings.artifact_path, exclusive=True):
        _assert_stopped(store)
        if store.get_signing_key(key_id) or path.exists() or path.is_symlink():
            raise RuntimeError("use a new signing key ID and an empty output path")
        signer = LocalEd25519Signer(path, key_id)
        store.ensure_signing_key(
            signer.trust_record(tenant_id=settings.tenant_id, revision=1),
            audit={"actorId": "local_operator", "action": "signing_key.created", "requestId": "offline_key_creation"},
        )
        return {"signingKeyId": key_id, "signingPrivateKeyPath": str(path.absolute()), "previousKeysRetained": True}


def run_keys():
    parser = argparse.ArgumentParser(prog="extrio-keys", description="Offline key operations; make a full backup first")
    parser.add_argument("command", choices=["initialize", "rotate-credentials", "create-signing", "set-signing-status"])
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--key-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status", choices=["retired", "compromised"])
    args = parser.parse_args()
    settings = get_settings()
    store = Store(settings.database_path, database_url=settings.database_url or "")
    try:
        if args.command == "initialize":
            result = initialize_keys(settings, store, offline=args.offline)
        elif args.command == "rotate-credentials":
            result = rotate_credentials(settings, store, offline=args.offline)
        elif args.command == "create-signing":
            if not args.key_id or not args.output:
                parser.error("create-signing requires --key-id and --output")
            result = create_signing_key(settings, store, args.key_id, args.output, offline=args.offline)
        else:
            if not args.offline or not args.key_id or not args.status:
                parser.error("set-signing-status requires --offline, --key-id and --status")
            with instance_lock(settings.artifact_path, exclusive=True):
                _assert_stopped(store)
                key = store.update_signing_key_status(args.key_id, args.status, actor_id="local_operator", request_id="offline_key_status")
                result = {"signingKeyId": key["id"], "status": key["status"], "revision": key["revision"]}
        print(json.dumps(result))
    except Exception as exc:
        print(f"key operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
