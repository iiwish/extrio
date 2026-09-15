import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from extrio.credentials import CredentialCipher, validate_stored_credentials
from extrio.integrity import LocalEd25519Signer
from extrio.store import utc_now

HEARTBEAT_SECONDS = 5
STALE_SECONDS = 20


def _code_digest():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob("*.py")):
        digest.update(str(path.relative_to(Path(__file__).parent)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


# Capture the loaded deployment once. Heartbeats must not adopt edited files.
CODE_DIGEST = _code_digest()


def deployment_digest(settings):
    configuration = {
        name: str(getattr(settings, name))
        for name in (
            "tenant_id",
            "artifact_path",
            "signing_private_key_path",
            "signing_key_id",
            "credential_encryption_key_path",
            "contracts_path",
            "allow_http_localhost",
            "worker_lease_seconds",
        )
    }
    contracts = hashlib.sha256()
    for path in sorted(settings.contracts_path.glob("*")):
        if path.is_file():
            contracts.update(path.name.encode())
            contracts.update(path.read_bytes())
    return hashlib.sha256(
        json.dumps({"code": CODE_DIGEST, "contracts": contracts.hexdigest(), "configuration": configuration}, sort_keys=True).encode()
    ).hexdigest()


class WorkerHeartbeat:
    def __init__(self, store, digest):
        self.store = store
        self.digest = digest
        self.id = uuid.uuid4().hex
        self.started_at = utc_now()

    def pulse(self):
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO worker_instances(id, deployment_digest, started_at, last_seen, status) VALUES(?, ?, ?, ?, 'running') "
                "ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, status='running'",
                (self.id, self.digest, self.started_at, utc_now()),
            )
            cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
            connection.execute("DELETE FROM worker_instances WHERE last_seen<?", (cutoff,))

    def stop(self):
        with self.store.transaction() as connection:
            connection.execute("UPDATE worker_instances SET status='stopped', last_seen=? WHERE id=?", (utc_now(), self.id))


def material_status(store, settings):
    try:
        validate_stored_credentials(store, CredentialCipher(settings.credential_encryption_key_path))
    except (ValueError, OSError):
        return {"ready": False, "reason": "credential_key_unavailable"}
    trust = store.get_signing_key(settings.signing_key_id)
    if trust or settings.signing_private_key_path.exists() or settings.signing_private_key_path.is_symlink():
        path = settings.signing_private_key_path
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
            return {"ready": False, "reason": "signing_key_unavailable"}
        try:
            public_key = LocalEd25519Signer(path, settings.signing_key_id).public_key_pem()
        except Exception:
            return {"ready": False, "reason": "signing_key_unavailable"}
        if trust and public_key != trust["publicKeyPem"]:
            return {"ready": False, "reason": "signing_key_mismatch"}
        if trust and trust["status"] != "trusted":
            return {"ready": False, "reason": "signing_key_not_trusted"}
    return {"ready": True, "reason": None}


def runtime_status(store, digest, settings=None):
    now = datetime.now(UTC)
    cutoff = (now - timedelta(seconds=STALE_SECONDS)).isoformat().replace("+00:00", "Z")
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT id, deployment_digest, last_seen FROM worker_instances WHERE status='running' AND last_seen>=? ORDER BY last_seen DESC",
            (cutoff,),
        ).fetchall()
        jobs = connection.execute(
            "SELECT status, COUNT(*) AS count FROM jobs WHERE status IN ('queued', 'processing') GROUP BY status"
        ).fetchall()
        oldest = connection.execute(
            "SELECT MIN(available_at) AS oldest FROM jobs WHERE status='queued' AND available_at<=?", (utc_now(),)
        ).fetchone()["oldest"]
    job_counts = {row["status"]: row["count"] for row in jobs}
    age = max(0, int((now - datetime.fromisoformat(oldest.replace("Z", "+00:00"))).total_seconds())) if oldest else 0
    mismatched = sum(row["deployment_digest"] != digest for row in rows)
    reason = "worker_unavailable" if not rows else "worker_deployment_mismatch" if mismatched else None
    if settings:
        materials = material_status(store, settings)
        reason = materials["reason"] or reason
    return {
        "ready": reason is None,
        "reason": reason,
        "liveWorkers": len(rows),
        "mismatchedWorkers": mismatched,
        "workers": [
            {"id": row["id"], "lastSeen": row["last_seen"], "deploymentMatches": row["deployment_digest"] == digest} for row in rows[:50]
        ],
        "queue": {"queuedJobs": job_counts.get("queued", 0), "runningJobs": job_counts.get("processing", 0), "oldestDueSeconds": age},
        "heartbeatMaxAgeSeconds": STALE_SECONDS,
        "checkedAt": now.isoformat().replace("+00:00", "Z"),
    }
