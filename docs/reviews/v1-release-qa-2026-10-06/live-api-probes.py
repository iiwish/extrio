"""Independent release probes; only accepts an owned local G4 QA instance."""

import argparse
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    args = parser.parse_args()
    root = args.instance.resolve()
    assert root.name.startswith("g4-qa-")
    state = json.loads((root / "state.json").read_text())
    assert (
        state["apiUrl"].startswith("http://127.0.0.1:")
        and state["syntheticModel"] is True
    )
    base = state["apiUrl"] + "/api/v1"
    credentials = json.loads((root / "qa-login.json").read_text())
    suffix = secrets.token_hex(5)
    results = []

    def check(label, callback):
        try:
            detail = callback()
            results.append({"case": label, "status": "passed", "detail": detail})
        except (AssertionError, httpx.HTTPError, ValueError, KeyError) as exc:
            results.append({"case": label, "status": "failed", "detail": str(exc)})

    def status(response, expected):
        assert response.status_code == expected, (
            f"expected {expected}, got {response.status_code}: {response.text[:300]}"
        )
        return {
            "httpStatus": response.status_code,
            "code": response.json().get("code") if response.content else None,
        }

    def write(client, method, path, body, key=None, headers=None):
        return client.request(
            method,
            path,
            json=body,
            headers={
                "Idempotency-Key": key or "qa-" + secrets.token_hex(12),
                **(headers or {}),
            },
        )

    with (
        httpx.Client(base_url=base, timeout=30) as admin,
        httpx.Client(base_url=base, timeout=30) as anonymous,
    ):
        status(admin.post("/auth/login", json=credentials), 200)
        for path in (
            "/collections",
            "/collectors",
            "/runs",
            "/items",
            "/items/export?format=csv",
            "/settings/models",
            "/users",
        ):
            check(
                "anonymous-denied:" + path,
                lambda path=path: status(anonymous.get(path), 401),
            )
        check(
            "first-admin-setup-closed",
            lambda: status(anonymous.post("/auth/setup", json=credentials), 409),
        )
        check(
            "cross-origin-mutation-denied",
            lambda: status(
                write(
                    admin,
                    "POST",
                    "/collections",
                    {"name": "QA", "intent": "QA"},
                    headers={"Origin": "https://attacker.invalid"},
                ),
                403,
            ),
        )
        check(
            "cross-site-mutation-denied",
            lambda: status(
                write(
                    admin,
                    "POST",
                    "/collections",
                    {"name": "QA", "intent": "QA"},
                    headers={"Sec-Fetch-Site": "cross-site"},
                ),
                403,
            ),
        )
        check(
            "missing-idempotency-rejected",
            lambda: status(
                admin.post("/collections", json={"name": "QA", "intent": "QA"}), 400
            ),
        )

        for label, body in (
            ("empty-name", {"name": " ", "intent": "QA"}),
            ("name-201", {"name": "x" * 201, "intent": "QA"}),
            ("numeric-name", {"name": 123, "intent": "QA"}),
            ("array-intent", {"name": "QA", "intent": []}),
            ("unknown-property", {"name": "QA", "intent": "QA", "tenantId": "other"}),
        ):
            check(
                "collection-validation:" + label,
                lambda body=body: status(
                    write(admin, "POST", "/collections", body), 422
                ),
            )
        check(
            "malformed-json",
            lambda: status(
                admin.post(
                    "/collections",
                    content="{",
                    headers={
                        "Content-Type": "application/json",
                        "Idempotency-Key": "qa-json-" + suffix,
                    },
                ),
                422,
            ),
        )
        for query in ("limit=-1", "limit=10001", "page=0"):
            check(
                "pagination-boundary:" + query,
                lambda query=query: status(admin.get("/items?" + query), 422),
            )

        for label, body in (
            (
                "numeric-name",
                {
                    "name": 123,
                    "intent": "QA",
                    "sourceUrl": "https://example.com/" + suffix,
                },
            ),
            (
                "array-name",
                {
                    "name": ["QA"],
                    "intent": "QA",
                    "sourceUrl": "https://example.com/" + suffix,
                },
            ),
            (
                "numeric-intent",
                {
                    "name": "QA",
                    "intent": 123,
                    "sourceUrl": "https://example.com/" + suffix,
                },
            ),
        ):
            check(
                "source-validation:" + label,
                lambda body=body: status(
                    write(admin, "POST", "/collectors", body), 422
                ),
            )
        for url in (
            "file:///etc/passwd",
            "https://169.254.169.254/latest/meta-data/",
            "https://10.0.0.1/",
            "https://user:password@example.com/",
            "javascript:alert(1)",
        ):
            check(
                "unsafe-source-rejected:" + url,
                lambda url=url: status(
                    write(
                        admin,
                        "POST",
                        "/collectors",
                        {"name": "QA", "intent": "QA", "sourceUrl": url},
                    ),
                    422,
                ),
            )

        body = {
            "name": "QA concurrent " + suffix,
            "intent": "Release idempotency probe",
        }
        key = "qa-concurrent-" + suffix
        with ThreadPoolExecutor(max_workers=12) as pool:
            replies = list(
                pool.map(
                    lambda _: write(admin, "POST", "/collections", body, key), range(12)
                )
            )

        def concurrency():
            assert all(reply.status_code == 201 for reply in replies), [
                reply.status_code for reply in replies
            ]
            ids = {reply.json()["id"] for reply in replies}
            assert len(ids) == 1, ids
            return {
                "requests": 12,
                "logicalResources": len(ids),
                "replayed": sum(
                    reply.headers.get("Idempotency-Replayed") == "true"
                    for reply in replies
                ),
            }

        check("concurrent-duplicate-create", concurrency)
        check(
            "idempotency-body-conflict",
            lambda: status(
                write(admin, "POST", "/collections", {**body, "name": "Other"}, key),
                409,
            ),
        )
        collection = next(reply.json() for reply in replies if reply.status_code == 201)
        cid = collection["id"]
        check(
            "optimistic-update",
            lambda: status(
                write(
                    admin,
                    "PATCH",
                    "/collections/" + cid,
                    {"revision": 1, "name": "QA revised " + suffix},
                ),
                200,
            ),
        )
        check(
            "stale-revision-rejected",
            lambda: status(
                write(
                    admin,
                    "PATCH",
                    "/collections/" + cid,
                    {"revision": 1, "name": "QA stale"},
                ),
                409,
            ),
        )
        check(
            "boolean-revision-rejected",
            lambda: status(
                write(
                    admin,
                    "PATCH",
                    "/collections/" + cid,
                    {"revision": True, "name": "QA stale"},
                ),
                422,
            ),
        )

        for role in ("viewer", "engineer", "reviewer"):
            password = secrets.token_urlsafe(24)
            user = write(
                admin,
                "POST",
                "/users",
                {
                    "username": "qa-" + role + "-" + suffix,
                    "password": password,
                    "role": role,
                },
            )
            status(user, 201)
            with httpx.Client(base_url=base, timeout=30) as client:
                status(
                    client.post(
                        "/auth/login",
                        json={
                            "username": user.json()["username"],
                            "password": password,
                        },
                    ),
                    200,
                )
                check(role + ":read-items", lambda: status(client.get("/items"), 200))
                check(
                    role + ":admin-write-denied",
                    lambda: status(write(client, "PUT", "/settings/models", {}), 403),
                )
                check(
                    role + ":create-user-denied",
                    lambda: status(write(client, "POST", "/users", {}), 403),
                )
                if role != "engineer":
                    check(
                        role + ":create-collection-denied",
                        lambda: status(
                            write(
                                client,
                                "POST",
                                "/collections",
                                {"name": "QA role", "intent": "QA"},
                            ),
                            403,
                        ),
                    )
                else:
                    check(
                        role + ":create-collection-allowed",
                        lambda: status(
                            write(
                                client,
                                "POST",
                                "/collections",
                                {"name": "QA engineer " + suffix, "intent": "QA"},
                            ),
                            201,
                        ),
                    )
                if role != "reviewer":
                    check(
                        role + ":publish-denied",
                        lambda: status(
                            write(
                                client,
                                "POST",
                                "/collections/" + cid + "/publish-version",
                                {},
                            ),
                            403,
                        ),
                    )
                if role == "viewer":
                    saved_cookie = dict(client.cookies)
                    check(
                        "disable-viewer",
                        lambda user=user: status(
                            write(
                                admin,
                                "PATCH",
                                "/users/" + user.json()["id"],
                                {"enabled": False},
                            ),
                            200,
                        ),
                    )
                    check(
                        "disabled-session-rejected",
                        lambda: status(client.get("/items"), 401),
                    )
                    check(
                        "disabled-cookie-replay-rejected",
                        lambda saved_cookie=saved_cookie: status(
                            anonymous.get("/items", cookies=saved_cookie), 401
                        ),
                    )
                if role == "engineer":
                    check(
                        "administrator-resets-engineer-password",
                        lambda user=user: status(
                            write(
                                admin,
                                "PATCH",
                                "/users/" + user.json()["id"],
                                {"password": secrets.token_urlsafe(24)},
                            ),
                            200,
                        ),
                    )
                    check(
                        "password-reset-revokes-session",
                        lambda: status(client.get("/items"), 401),
                    )

        admin_id = admin.get("/auth/state").json()["user"]["id"]
        check(
            "last-administrator-demotion-rejected",
            lambda: status(
                write(admin, "PATCH", "/users/" + admin_id, {"role": "viewer"}), 409
            ),
        )
        check(
            "self-disable-rejected",
            lambda: status(
                write(admin, "PATCH", "/users/" + admin_id, {"enabled": False}), 409
            ),
        )

        journey_path = root / "browser-journey.json"
        if journey_path.exists():
            journey = json.loads(journey_path.read_text())
            source_id = urlsplit(journey["collectorUrl"]).path.rsplit("/", 1)[-1]
            model_before = (root / "synthetic-model.jsonl").read_bytes()
            key = "qa-production-run-" + suffix
            started = admin.post(
                "/collectors/" + source_id + "/runs", headers={"Idempotency-Key": key}
            )
            status(started, 202)
            replayed = admin.post(
                "/collectors/" + source_id + "/runs", headers={"Idempotency-Key": key}
            )

            def replay_run():
                status(replayed, 202)
                assert replayed.json()["id"] == started.json()["id"]
                return {"sameOperation": True}

            check("run-request-idempotency", replay_run)
            run_id = started.json()["resourceId"]
            for _ in range(120):
                run = admin.get("/runs/" + run_id).json()
                if run["status"] in {
                    "succeeded",
                    "failed",
                    "partial",
                    "cancelled",
                    "timed_out",
                }:
                    break
                time.sleep(0.5)

            def runtime_without_model():
                assert run["status"] == "succeeded", run["status"]
                assert run["acceptedCount"] == 1, run["acceptedCount"]
                assert (root / "synthetic-model.jsonl").read_bytes() == model_before
                return {
                    "runStatus": run["status"],
                    "acceptedCount": run["acceptedCount"],
                    "additionalModelCalls": 0,
                }

            check("published-runtime-does-not-call-model", runtime_without_model)
        else:
            results.append(
                {
                    "case": "published-runtime-does-not-call-model",
                    "status": "not-run",
                    "detail": "browser journey not available",
                }
            )

        saved_cookie = dict(admin.cookies)
        check("logout", lambda: status(admin.post("/auth/logout"), 200))
        check(
            "logout-cookie-replay-rejected",
            lambda: status(anonymous.get("/items", cookies=saved_cookie), 401),
        )

    report = {
        "database": state["database"],
        "cases": results,
        "passed": sum(row["status"] == "passed" for row in results),
        "failed": sum(row["status"] == "failed" for row in results),
        "notRun": sum(row["status"] == "not-run" for row in results),
    }
    (root / "live-api-probes.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(1 if report["failed"] else 0)


if __name__ == "__main__":
    main()
