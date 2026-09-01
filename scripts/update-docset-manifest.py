#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/releases/v0.2-docset-manifest.json"
VERSION_OVERRIDES = {
    "docs/SSOT.md": "v0.37.0",
    "docs/product-contract.md": "v0.37.0",
    "docs/domain-model.md": "v0.7.0",
    "docs/contracts/gather-spec.md": "v1.5.0",
    "docs/runtime-contract.md": "v0.6.0",
    "docs/architecture/ADR-002-orchestration-storage.md": "v1.2.0",
    "docs/frontend-prototype.md": "v1.31.0",
    "docs/backend-vertical-slice.md": "v1.11.0",
    "docs/contracts/api-contract.md": "v1.11.0",
    "docs/releases/v0.2-acceptance.md": "v0.37.0",
}
DOCSET_VERSION = "v0.37.0"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_manifest(source: dict) -> dict:
    data = deepcopy(source)
    data["docsetVersion"] = DOCSET_VERSION
    entries = data["authoritativeFiles"]
    known = {entry["path"] for entry in entries}
    if "docs/backend-vertical-slice.md" not in known:
        entries.insert(-1, {"path": "docs/backend-vertical-slice.md", "version": "v1.0.0", "sha256": ""})

    for group in (entries, data["verificationFixtures"]):
        for entry in group:
            entry["version"] = VERSION_OVERRIDES.get(entry["path"], entry["version"])
            entry["sha256"] = digest(ROOT / entry["path"])
    return data


def comparable(data: dict) -> dict:
    value = deepcopy(data)
    value.pop("generatedAt", None)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Update or verify the Extrio documentation manifest.")
    parser.add_argument("--check", action="store_true", help="fail when the manifest is stale")
    args = parser.parse_args()

    current = json.loads(MANIFEST.read_text())
    expected = expected_manifest(current)
    if args.check:
        if comparable(current) != comparable(expected):
            print("docs/releases/v0.2-docset-manifest.json is stale", file=sys.stderr)
            return 1
        print("documentation manifest is current")
        return 0

    expected["generatedAt"] = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    MANIFEST.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
