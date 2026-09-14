#!/usr/bin/env python3
"""Isolated authenticated API/Worker with an explicitly synthetic HTTPS model."""

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import signal
import ssl
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import psycopg
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from psycopg import sql


class FixtureHandler(BaseHTTPRequestHandler):
    def respond(self, body, content_type="application/json", status=200):
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/robots.txt":
            self.respond("User-agent: *\nAllow: /\n", "text/plain")
        elif self.path.startswith("/notice"):
            self.respond(
                "<!doctype html><html><body><main><h1>G4 public fixture notice</h1>"
                "<p>Deterministic integration fixture.</p></main></body></html>",
                "text/html; charset=utf-8",
            )
        else:
            self.respond("not found", "text/plain", 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if self.path == "/hook" and 0 < length < 1024 * 1024:
            body = self.rfile.read(length)
            payload = json.loads(body)
            signature = "sha256=" + hmac.new(b"g4-fixture-webhook", body, hashlib.sha256).hexdigest()
            valid = (
                hmac.compare_digest(self.headers.get("X-Extrio-Signature", ""), signature)
                and self.headers.get("Content-Digest") == "sha256=" + hashlib.sha256(body).hexdigest()
                and self.headers.get("Idempotency-Key") == payload.get("deliveryId")
            )
            with self.server.record_lock, (self.server.root / "receiver.jsonl").open("a") as handle:
                handle.write(json.dumps({"deliveryId": payload.get("deliveryId"), "valid": valid}) + "\n")
            self.respond("{}", status=200 if valid else 400)
            return
        if self.path != "/v1/chat/completions" or not 0 < length < 1024 * 1024:
            self.respond("{}", status=400)
            return
        payload = json.loads(self.rfile.read(length))
        evidence = json.loads(payload["messages"][-1]["content"])
        phase = "compile" if "discoveryPlan" in evidence else "discover"
        field = {
            "selector": "css:h1::text",
            "label": "Title",
            "valueType": "string",
            "required": True,
            "onError": "reject",
            "multipleMatchPolicy": "first",
            "transforms": [],
        }
        plan = {
            "mode": "single",
            "transport": "http",
            "list": {"responseType": "html", "itemsSelector": "css:body", "pagination": {"type": "none"}, "fields": {"title": field}},
            "bindings": {"title": "list.title"},
            "identityFields": ["title"],
            "fingerprintFields": ["title"],
            "rationale": "Synthetic G4 protocol fixture, not a real model result",
        }
        with self.server.record_lock, (self.server.root / "synthetic-model.jsonl").open("a") as handle:
            handle.write(
                json.dumps({"at": datetime.now(UTC).isoformat(), "phase": phase, "model": payload["model"], "synthetic": True}) + "\n"
            )
        self.respond(
            json.dumps({"choices": [{"message": {"content": json.dumps(plan)}}], "usage": {"prompt_tokens": 0, "completion_tokens": 0}})
        )

    def log_message(self, *args):
        pass


def certificate(root):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "G4 localhost fixture")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = root / "fixture-ca.pem", root / "fixture-tls.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return cert_path, context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=8048)
    parser.add_argument("--web-port", type=int, default=5198)
    parser.add_argument("--postgresql", action="store_true", help="create an owned temporary database on EXTRIO_TEST_DATABASE_URL")
    parser.add_argument("--duration", type=int, default=14400)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists() or not root.name.startswith("g4-qa-") or not 0 < args.duration <= 14400:
        parser.error("Requires a new g4-qa-* directory and at most four hours")
    pg_admin = os.environ.get("EXTRIO_TEST_DATABASE_URL") if args.postgresql else None
    if args.postgresql and not pg_admin:
        parser.error("PostgreSQL requires an explicitly isolated EXTRIO_TEST_DATABASE_URL")
    root.mkdir(parents=True, mode=0o700)
    cert_path, tls = certificate(root)
    servers = [ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler) for _ in range(2)]
    servers[1].socket = tls.wrap_socket(servers[1].socket, server_side=True)
    for server in servers:
        server.root, server.record_lock = root, threading.Lock()
        threading.Thread(target=server.serve_forever, daemon=True).start()
    source = f"http://127.0.0.1:{servers[0].server_port}/notice"
    model = f"https://127.0.0.1:{servers[1].server_port}/v1"
    env = {
        **os.environ,
        "EXTRIO_DATABASE_URL": "",
        "EXTRIO_DATABASE_PATH": str(root / "extrio.db"),
        "EXTRIO_ARTIFACT_PATH": str(root / "artifacts"),
        "EXTRIO_SIGNING_PRIVATE_KEY_PATH": str(root / "keys/signing.pem"),
        "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": str(root / "keys/credentials.key"),
        "EXTRIO_ALLOW_HTTP_LOCALHOST": "true",
        "EXTRIO_AUTH_ENABLED": "true",
        "EXTRIO_SEED_DEMO": "false",
        "EXTRIO_HOST": "127.0.0.1",
        "EXTRIO_PORT": str(args.api_port),
        "EXTRIO_MODEL_API_KEY": "",
        "SSL_CERT_FILE": str(cert_path),
        "EXTRIO_CORS_ORIGINS": f"http://127.0.0.1:{args.web_port}",
    }
    children, logs = [], []
    database_name = None
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        if pg_admin:
            name = "extrio_g4_qa_" + uuid.uuid4().hex[:12]
            with psycopg.connect(pg_admin, autocommit=True) as admin:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            database_name = name
            env["EXTRIO_DATABASE_URL"] = pg_admin.rsplit("/", 1)[0] + "/" + name
        for name in ("app", "worker"):
            log = (root / f"{name}.log").open("a")
            logs.append(log)
            children.append(subprocess.Popen([sys.executable, "-m", "extrio." + name], env=env, stdout=log, stderr=subprocess.STDOUT))
        api = f"http://127.0.0.1:{args.api_port}"
        with httpx.Client(base_url=api + "/api/v1", timeout=15) as client:
            for _ in range(120):
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("QA process exited during startup")
                try:
                    if client.get("/auth/state").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.25)
            credentials = {"username": "g4-qa-admin", "password": secrets.token_urlsafe(24)}
            with open(root / "qa-login.json", "x", opener=lambda p, f: os.open(p, f, 0o600)) as handle:
                json.dump(credentials, handle)
            client.post("/auth/setup", json={**credentials, "displayName": "G4 QA"}).raise_for_status()
            response = client.put(
                "/settings/models",
                json={
                    "providers": [
                        {
                            "id": "provider_fixture",
                            "name": "Synthetic G4 protocol fixture",
                            "provider": "openai",
                            "baseUrl": model,
                            "enabled": True,
                            "apiKey": "local-fixture-no-secret",
                        }
                    ],
                    "models": [{"id": "model_fixture", "providerId": "provider_fixture", "modelId": "synthetic-g4", "enabled": True}],
                    "defaultModelId": "model_fixture",
                },
                headers={"Idempotency-Key": "g4-fixture-model-configuration"},
            )
            response.raise_for_status()
        state = {
            "supervisorPid": os.getpid(),
            "apiPid": children[0].pid,
            "workerPid": children[1].pid,
            "apiUrl": api,
            "sourceUrl": source,
            "hookUrl": source.rsplit("/", 1)[0] + "/hook",
            "modelUrl": model,
            "syntheticModel": True,
            "database": "postgresql" if pg_admin else "sqlite",
            "databaseName": database_name,
        }
        (root / "state.json").write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps(state), flush=True)
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline and not stop.wait(1):
            if any(child.poll() is not None for child in children):
                raise RuntimeError("QA child process stopped")
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for server in servers:
            server.shutdown()
            server.server_close()
        for log in logs:
            log.close()
        if database_name:
            with psycopg.connect(pg_admin, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))


if __name__ == "__main__":
    main()
