"""Local sampled snapshots, not complete replayable ArtifactManifests."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,160}$")
SAFE_FILE = re.compile(r"^(list|detail)-[0-9]+\.html$")
MANIFEST = "local-evidence.json"


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class LocalEvidence:
    def __init__(self, root: Path, run_id: str, retention_days: int, reference: str = "attempt_1"):
        if not SAFE_ID.fullmatch(run_id) or not SAFE_ID.fullmatch(reference):
            raise ValueError("invalid local evidence reference")
        self.directory = root / run_id / reference
        if self.directory.is_symlink() or self.directory.parent.is_symlink():
            raise ValueError("invalid local evidence directory")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.reference = reference
        self.retention_days = max(0, retention_days)
        self.mode = "sampled" if self.retention_days else "metadata_only"
        self.files = {}

    def write(self, filename: str, source: str) -> None:
        if not SAFE_FILE.fullmatch(filename):
            raise ValueError("invalid snapshot name")
        if not self.retention_days:
            return
        payload = source.encode("utf-8")
        path = self.directory / filename
        if path.is_symlink():
            raise ValueError("invalid snapshot file")
        path.write_bytes(payload)
        self.files[filename] = {"name": filename, "digest": digest(payload), "bytes": len(payload)}

    def finish(self, *, complete: bool) -> str:
        now = datetime.now(UTC)
        manifest = {
            "schemaVersion": "extrio.local-evidence.v1",
            "runId": self.run_id,
            "reference": self.reference,
            "mode": self.mode,
            "complete": complete,
            "recordedAt": now.isoformat(),
            "expiresAt": (now + timedelta(days=self.retention_days)).isoformat() if self.retention_days else None,
            "files": [self.files[name] for name in sorted(self.files)],
        }
        payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
        path = self.directory / MANIFEST
        if path.is_symlink():
            raise ValueError("invalid local evidence manifest")
        path.write_bytes(payload)
        return digest(payload)


def evidence_status(root: Path, run: dict, *, now: datetime | None = None) -> dict:
    result = {
        "mode": "metadata_only",
        "state": "missing",
        "fileCount": 0,
        "totalBytes": 0,
        "expiresAt": None,
        "canReplay": False,
        "replayReason": "complete_replayable_evidence_unavailable",
    }
    reference = run.get("localEvidenceRef", "attempt_1")
    if not SAFE_ID.fullmatch(str(run["id"])) or not SAFE_ID.fullmatch(str(reference)):
        return {**result, "state": "invalid"}
    directory = root / run["id"] / reference
    path = directory / MANIFEST
    if directory.is_symlink() or directory.parent.is_symlink() or path.is_symlink():
        return {**result, "state": "invalid"}
    if not path.is_file():
        return result
    try:
        if path.stat().st_size > 20_000_000:
            raise ValueError("manifest size")
        payload = path.read_bytes()
        if not run.get("localEvidenceDigest"):
            return {**result, "state": "incomplete"}
        if digest(payload) != run["localEvidenceDigest"]:
            raise ValueError("manifest digest")
        manifest = json.loads(payload)
        if manifest["schemaVersion"] != "extrio.local-evidence.v1" or manifest["runId"] != run["id"] or manifest["reference"] != reference:
            raise ValueError("manifest identity")
        if manifest["mode"] not in {"sampled", "metadata_only"}:
            raise ValueError("manifest mode")
        files = manifest["files"]
        result.update(mode=manifest["mode"], fileCount=len(files), expiresAt=manifest["expiresAt"])
        if result["expiresAt"] and datetime.fromisoformat(result["expiresAt"]) <= (now or datetime.now(UTC)):
            return {**result, "state": "expired"}
        for member in files:
            if not SAFE_FILE.fullmatch(member["name"]):
                raise ValueError("member name")
            path = directory / member["name"]
            if path.is_symlink() or not path.is_file() or path.stat().st_size != member["bytes"]:
                raise ValueError("member missing")
            if digest(path.read_bytes()) != member["digest"]:
                raise ValueError("member digest")
            result["totalBytes"] += member["bytes"]
        result["state"] = "available" if manifest["complete"] else "incomplete"
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return {**result, "state": "invalid"}


def prune_expired_evidence(root: Path, *, now: datetime | None = None) -> dict:
    result = {"removedFiles": 0, "removedBytes": 0, "invalidManifests": 0}
    if not root.is_dir() or root.is_symlink():
        return result
    for path in root.glob(f"*/*/{MANIFEST}"):
        directory = path.parent
        try:
            if any(part.is_symlink() for part in (path, directory, directory.parent)) or path.stat().st_size > 20_000_000:
                raise ValueError("invalid evidence path")
            manifest = json.loads(path.read_bytes())
            if (
                manifest["schemaVersion"] != "extrio.local-evidence.v1"
                or manifest["runId"] != directory.parent.name
                or manifest["reference"] != directory.name
            ):
                raise ValueError("invalid evidence identity")
            if not manifest["expiresAt"] or datetime.fromisoformat(manifest["expiresAt"]) > (now or datetime.now(UTC)):
                continue
            members = manifest["files"]
            if not all(SAFE_FILE.fullmatch(member["name"]) for member in members):
                raise ValueError("invalid evidence member")
            for member in members:
                raw = directory / member["name"]
                if raw.is_symlink():
                    raise ValueError("invalid evidence member")
                if raw.is_file():
                    size = raw.stat().st_size
                    raw.unlink()
                    result["removedFiles"] += 1
                    result["removedBytes"] += size
        except (OSError, ValueError, TypeError, KeyError):
            result["invalidManifests"] += 1
    return result
