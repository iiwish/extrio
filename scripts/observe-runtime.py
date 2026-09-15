#!/usr/bin/env python3
"""Bounded, local-only scheduler/Worker/Webhook observation with owned processes."""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx


def stamp():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_state(root, value):
    temporary = root / "state.json.tmp"
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(root / "state.json")


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path)
        now = datetime.now(UTC).replace(second=0, microsecond=0).isoformat()
        if path.path == "/robots.txt":
            content = "User-agent: *\nAllow: /\n"
        elif path.path == "/demo/tenders":
            rows = (
                '<li><a class="notice-title" href="/demo/tenders/one">Observation notice</a><time datetime="'
                + now
                + '"></time></li>'
            )
            if parse_qs(path.query).get("page", ["1"])[0] != "1":
                rows = ""
            content = '<ul class="notice-list">' + rows + "</ul>"
        elif path.path == "/demo/tenders/one":
            content = (
                '<h1 class="notice-title">Observation notice</h1><div class="meta"><time datetime="'
                + now
                + '"></time></div><div class="notice-content">Fixture revision '
                + now
                + '</div><span data-field="buyer">G3 fixture</span><span data-field="region">Local</span>'
                '<div class="notice-budget"><span class="amount">100</span></div>'
            )
        else:
            self.send_error(404)
            return
        body = content.encode()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain" if path.path == "/robots.txt" else "text/html; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/hook":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 1024 * 1024:
            self.send_error(413)
            return
        body = self.rfile.read(length)
        expected = (
            "sha256="
            + hmac.new(self.server.secret.encode(), body, hashlib.sha256).hexdigest()
        )
        digest = "sha256=" + hashlib.sha256(body).hexdigest()
        payload = json.loads(body)
        delivery_id = self.headers.get("Idempotency-Key")
        valid = (
            hmac.compare_digest(self.headers.get("X-Extrio-Signature", ""), expected)
            and self.headers.get("Content-Digest") == digest
            and delivery_id == payload.get("deliveryId")
        )
        with self.server.record_lock:
            with (self.server.root / "receiver.jsonl").open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "at": stamp(),
                            "deliveryId": delivery_id,
                            "valid": valid,
                            "bytes": length,
                            "digest": digest,
                        }
                    )
                    + "\n"
                )
            self.server.received += 1
            self.server.invalid += int(not valid)
        self.send_response(200 if valid else 400)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="new g3-observation-* directory only"
    )
    parser.add_argument("--duration-seconds", type=float, default=72 * 3600)
    parser.add_argument("--sample-seconds", type=float, default=60)
    parser.add_argument("--api-port", type=int, default=8038)
    parser.add_argument("--collectors", type=int, default=3)
    args = parser.parse_args()
    root = args.output.resolve()
    if (
        not root.name.startswith("g3-observation-")
        or root.exists()
        or not 0 < args.sample_seconds <= args.duration_seconds
        or not 1 <= args.collectors <= 10
    ):
        parser.error(
            "Use a new g3-observation-* directory and positive, bounded parameters"
        )
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", args.api_port))
    root.mkdir(parents=True, mode=0o700)
    env = dict(
        os.environ,
        EXTRIO_DATABASE_URL="",
        EXTRIO_DATABASE_PATH=str(root / "extrio.db"),
        EXTRIO_ARTIFACT_PATH=str(root / "artifacts"),
        EXTRIO_SIGNING_PRIVATE_KEY_PATH=str(root / "keys/signing.pem"),
        EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH=str(root / "keys/credentials.key"),
        EXTRIO_ALLOW_HTTP_LOCALHOST="true",
        EXTRIO_AUTH_ENABLED="true",
        EXTRIO_SEED_DEMO="false",
        EXTRIO_HOST="127.0.0.1",
        EXTRIO_PORT=str(args.api_port),
        EXTRIO_SCHEDULE_POLL_SECONDS="5",
        EXTRIO_MODEL_API_KEY="",
    )
    os.environ.update(env)
    from benchmark import setup_collectors
    from extrio.app import store
    from extrio.config import get_settings
    from extrio.credentials import CredentialCipher
    from extrio.runtime_health import deployment_digest

    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    receiver = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    receiver.root, receiver.secret = root, secrets.token_urlsafe(32)
    receiver.record_lock = threading.Lock()
    receiver.received = receiver.invalid = 0
    threading.Thread(target=receiver.serve_forever, daemon=True).start()
    source = f"http://127.0.0.1:{receiver.server_port}"
    children, logs = {}, []
    state = {
        "status": "starting",
        "supervisorPid": os.getpid(),
        "createdAt": stamp(),
        "apiUrl": f"http://127.0.0.1:{args.api_port}",
        "fixtureUrl": source,
        "durationSeconds": args.duration_seconds,
        "sampleSeconds": args.sample_seconds,
        "collectors": args.collectors,
        "cron": "*/5 * * * *",
        "deploymentDigest": deployment_digest(get_settings()),
        "samples": 0,
        "scope": "local SQLite, real HTTP/API/scheduler/Worker and signed receiver; no external sources or models",
    }
    write_state(root, state)
    try:
        ids = setup_collectors(args.collectors, source + "/demo/tenders", "127.0.0.1")
        cipher = CredentialCipher(get_settings().credential_encryption_key_path)
        for collector_id in ids:
            store.create_sink(
                collector_id,
                cipher=cipher,
                url=source + "/hook",
                secret=receiver.secret,
            )
            store.save_schedule(
                collector_id,
                {
                    "enabled": True,
                    "cronExpression": "*/5 * * * *",
                    "timezone": "Asia/Shanghai",
                    "overlapPolicy": "forbid",
                },
            )
        for name, module in (("api", "extrio.app"), ("worker", "extrio.worker")):
            log = (root / f"{name}.log").open("a")
            logs.append(log)
            children[name] = subprocess.Popen(
                [sys.executable, "-m", module],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        state["processes"] = {name: child.pid for name, child in children.items()}
        with httpx.Client(base_url=state["apiUrl"], timeout=10) as client:
            deadline = time.monotonic() + 60
            while not stop.is_set() and time.monotonic() < deadline:
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if any(child.poll() is not None for child in children.values()):
                    raise RuntimeError("startup process failed")
                stop.wait(0.5)
            else:
                raise RuntimeError("startup readiness deadline exceeded")
            login = {
                "username": "observation-admin",
                "password": secrets.token_urlsafe(24),
            }
            with open(
                root / "login.json", "x", opener=lambda p, f: os.open(p, f, 0o600)
            ) as handle:
                json.dump(login, handle)
            client.post(
                "/api/v1/auth/setup", json={**login, "displayName": "G3 Observation"}
            ).raise_for_status()
            for collector_id in ids:
                client.post(
                    f"/api/v1/collectors/{collector_id}/runs",
                    headers={"Idempotency-Key": "observation-warmup-" + collector_id},
                ).raise_for_status()
            start = previous = time.time()
            state.update(
                status="observing",
                startedAt=stamp(),
                targetEndAt=datetime.fromtimestamp(
                    start + args.duration_seconds, UTC
                ).isoformat(),
                collectorIds=ids,
            )
            write_state(root, state)
            while not stop.is_set():
                now = time.time()
                response = client.get("/api/v1/runtime")
                if response.status_code == 401:
                    client.post("/api/v1/auth/login", json=login).raise_for_status()
                    response = client.get("/api/v1/runtime")
                response.raise_for_status()
                with store.connect() as connection:
                    counts = {
                        table: {
                            row["status"]: row["n"]
                            for row in connection.execute(
                                f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY status"
                            ).fetchall()
                        }
                        for table in ("deliveries", "schedule_occurrences")
                    }
                    counts["runs"] = {
                        row["status"]: row["n"]
                        for row in connection.execute(
                            "SELECT json_extract(data, '$.status') AS status, COUNT(*) AS n "
                            "FROM runs GROUP BY json_extract(data, '$.status')"
                        ).fetchall()
                    }
                    lag_rows = connection.execute(
                        "SELECT scheduled_at, updated_at FROM schedule_occurrences WHERE status='dispatched'"
                    ).fetchall()
                    lag = [
                        max(
                            0,
                            (
                                datetime.fromisoformat(
                                    row["updated_at"].replace("Z", "+00:00")
                                )
                                - datetime.fromisoformat(
                                    row["scheduled_at"].replace("Z", "+00:00")
                                )
                            ).total_seconds(),
                        )
                        for row in lag_rows
                    ]
                sample = {
                    "at": stamp(),
                    "elapsedSeconds": now - start,
                    "sampleGapSeconds": now - previous,
                    "runtime": response.json(),
                    **counts,
                    "maxScheduleDispatchSeconds": max(lag, default=None),
                    "receiverRequests": receiver.received,
                    "invalidSignatures": receiver.invalid,
                    "processExitCodes": {
                        name: child.poll() for name, child in children.items()
                    },
                }
                with (root / "samples.jsonl").open("a") as handle:
                    handle.write(json.dumps(sample) + "\n")
                state.update(
                    samples=state["samples"] + 1,
                    lastSampleAt=sample["at"],
                    lastSample=sample,
                )
                write_state(root, state)
                if any(child.poll() is not None for child in children.values()):
                    raise RuntimeError("owned process exited during observation")
                if now - start >= args.duration_seconds:
                    state["status"] = "completed_pending_analysis"
                    break
                previous = now
                stop.wait(
                    min(
                        args.sample_seconds,
                        max(0, start + args.duration_seconds - time.time()),
                    )
                )
            else:
                state["status"] = "stopped_pending_analysis"
    except Exception as exc:
        state.update(status="failed", errorType=type(exc).__name__, error=str(exc))
        raise
    finally:
        for child in children.values():
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children.values():
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        receiver.shutdown()
        receiver.server_close()
        for log in logs:
            log.close()
        state["finishedAt"] = stamp()
        write_state(root, state)
        print(
            json.dumps({key: state[key] for key in ("status", "samples", "finishedAt")})
        )


if __name__ == "__main__":
    main()
