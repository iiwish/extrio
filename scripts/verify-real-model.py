#!/usr/bin/env python3
"""One explicitly authorized real-model exploration in disposable storage."""

import argparse
import asyncio
import json
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration-db", type=Path, required=True)
    parser.add_argument("--credential-key", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-model-call", action="store_true", required=True)
    args = parser.parse_args()
    source = urlsplit(args.source_url)
    if source.scheme not in {"http", "https"} or not source.hostname or source.username or source.password:
        parser.error("use a public HTTP(S) source without embedded credentials")
    if args.output.exists():
        parser.error("output already exists; preserve the previous attempt")

    # Read configuration only, never initialize or migrate the user's database.
    with sqlite3.connect(f"{args.configuration_db.resolve().as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT key, data FROM platform_settings WHERE key IN (?, ?)",
            ("model-configurations", "model-provider-credentials"),
        ).fetchall()
    saved = {key: json.loads(data) for key, data in rows}
    configuration = saved["model-configurations"]
    selected = next(row for row in configuration["models"] if row["id"] == configuration["defaultModelId"])
    provider = next(row for row in configuration["providers"] if row["id"] == selected["providerId"])
    from extrio.credentials import CredentialCipher

    encrypted = saved["model-provider-credentials"]["credentials"][provider["id"]]
    secret = CredentialCipher(args.credential_key.resolve()).decrypt(encrypted)
    with tempfile.TemporaryDirectory(prefix="extrio-real-model-") as temporary:
        root = Path(temporary)
        os.environ.update({
            "EXTRIO_DATABASE_URL": f"sqlite:///{root / 'state.db'}",
            "EXTRIO_DATABASE_PATH": str(root / "state.db"),
            "EXTRIO_ARTIFACT_PATH": str(root / "artifacts"),
            "EXTRIO_SIGNING_PRIVATE_KEY_PATH": str(root / "signing.pem"),
            "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": str(root / "credentials.key"),
            "EXTRIO_AUTH_ENABLED": "true",
            "EXTRIO_SEED_DEMO": "false",
        })
        import extrio.app as app_module
        from extrio.worker import Worker
        from fastapi.testclient import TestClient

        with TestClient(app_module.app) as client:
            def command(method, path, body):
                response = client.request(method, "/api/v1" + path, json=body,
                                          headers={"Idempotency-Key": uuid.uuid4().hex})
                if response.is_error:
                    raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
                return response.json()

            command("POST", "/auth/setup", {"username": "release-check", "password": uuid.uuid4().hex})
            command("PUT", "/settings/models", {
                "providers": [{"id": "release-provider", "name": "Release validation",
                               "provider": provider["provider"], "baseUrl": provider["baseUrl"],
                               "enabled": True, "apiKey": secret}],
                "models": [{"id": "release-model", "providerId": "release-provider",
                            "modelId": selected["modelId"], "enabled": True}],
                "defaultModelId": "release-model",
            })
            del secret
            collection = command("POST", "/collections", {
                "name": "Release real-source validation",
                "intent": "Collect public notice titles and detail URLs from the list, then extract the notice body from each detail page."})
            path = f"/collections/{collection['id']}"
            updated = command("PATCH", path, {"revision": collection["revision"], "fieldDraft": {"fields": [{
                "key": "title", "label": "Title", "type": "string", "required": True,
                "identity": False, "fingerprint": True, "description": "Public notice title",
            }, {
                "key": "detailUrl", "label": "Detail URL", "type": "url", "required": True,
                "identity": True, "fingerprint": False, "description": "Absolute URL of the notice detail page",
            }, {
                "key": "content", "label": "Notice body", "type": "string", "required": True,
                "identity": False, "fingerprint": True, "description": "Notice body text from the detail page",
            }]}})
            command("POST", path + "/publish-version", {"revision": updated["revision"]})
            batch = command("POST", "/collectors/batch", {
                "collectionId": collection["id"], "collectionName": collection["name"],
                "intent": collection["intent"], "sources": [{"entryUrl": args.source_url, "mode": "exact"}]})
            collector = batch["results"][0]["collector"]
            operation = command("POST", f"/collectors/{collector['id']}/explorations", {})
            job = app_module.store.claim_job(300)
            assert job and job["operationId"] == operation["id"]
            worker = Worker()
            try:
                asyncio.run(worker.process(job))
            except Exception as exc:  # noqa: BLE001 - mirror the worker's terminal failure handling
                worker.fail(job, exc)
            detail = client.get(f"/api/v1/collectors/{collector['id']}").json()
            ai_run_id = client.get(operation["statusUrl"]).json()["aiRunId"]
            ai_run = client.get(f"/api/v1/ai-runs/{ai_run_id}").json()
            candidate = detail.get("candidate") or {}
            result = {
                "sourceUrl": args.source_url, "model": selected["modelId"],
                "providerHost": urlsplit(provider["baseUrl"]).hostname,
                "collectorStatus": detail["status"], "aiRun": ai_run,
                "candidate": candidate, "published": bool(detail.get("activeRuleVersion")),
                "scope": "One isolated real-model exploration; no automatic publication or retries",
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"status": detail["status"], "model": selected["modelId"],
                              "published": result["published"], "output": str(args.output)}))
            if detail["status"] != "ready_review" or result["published"]:
                raise SystemExit(1)


if __name__ == "__main__":
    main()
