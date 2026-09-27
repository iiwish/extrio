#!/usr/bin/env python3
"""One explicitly authorized real-model exploration in disposable storage."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    credentials = parser.add_mutually_exclusive_group(required=True)
    credentials.add_argument("--configuration-db", type=Path)
    credentials.add_argument("--api-key-stdin", action="store_true", help="read one secret line from stdin, never a CLI argument")
    parser.add_argument("--credential-key", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--provider", choices=("openai", "deepseek", "custom"), default="openai")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-model-call", action="store_true", required=True)
    args = parser.parse_args(argv)
    source = urlsplit(args.source_url)
    if source.scheme not in {"http", "https"} or not source.hostname or source.username or source.password:
        parser.error("use a public HTTP(S) source without embedded credentials")
    if args.output.exists():
        parser.error("output already exists; preserve the previous attempt")
    if args.configuration_db:
        if not args.credential_key or args.base_url or args.model:
            parser.error("configuration-db requires credential-key and cannot be mixed with direct model settings")
    else:
        endpoint = urlsplit(args.base_url or "")
        if (not args.model or endpoint.scheme != "https" or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or args.credential_key):
            parser.error("stdin credentials require model and a clean HTTPS base-url without embedded credentials")
    return args


def read_model_configuration(args):
    if args.api_key_stdin:
        secret = sys.stdin.readline().strip()
        if not secret:
            raise ValueError("API key input is empty")
        return {"provider": args.provider, "baseUrl": args.base_url.rstrip("/")}, {"modelId": args.model}, secret

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
    return provider, selected, secret


def isolated_environment(root):
    return {
        "EXTRIO_DATABASE_FROM_PG_ENV": "false",
        "EXTRIO_DATABASE_URL": f"sqlite:///{root / 'state.db'}",
        "EXTRIO_DATABASE_PATH": str(root / "state.db"),
        "EXTRIO_DATABASE_AUTO_MIGRATE": "true",
        "EXTRIO_ARTIFACT_PATH": str(root / "artifacts"),
        "EXTRIO_SIGNING_PRIVATE_KEY_PATH": str(root / "signing.pem"),
        "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": str(root / "credentials.key"),
        "EXTRIO_AUTH_ENABLED": "true",
        "EXTRIO_AUTH_COOKIE_SECURE": "false",
        "EXTRIO_ALLOW_HTTP_PUBLIC": "true",
        "EXTRIO_ALLOW_HTTP_LOCALHOST": "false",
        "EXTRIO_MODEL_API_KEY": "",
        "EXTRIO_SEED_DEMO": "false",
    }


def main():
    args = parse_args()
    provider, selected, secret = read_model_configuration(args)
    with tempfile.TemporaryDirectory(prefix="extrio-real-model-") as temporary:
        root = Path(temporary)
        os.environ.update(isolated_environment(root))
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
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(result, output, ensure_ascii=False, indent=2)
                output.write("\n")
            print(json.dumps({"status": detail["status"], "model": selected["modelId"],
                              "published": result["published"], "output": str(args.output)}))
            if detail["status"] != "ready_review" or result["published"]:
                raise SystemExit(1)


if __name__ == "__main__":
    main()
