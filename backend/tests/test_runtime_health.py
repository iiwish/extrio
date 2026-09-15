from test_collection_versions import client as client

import extrio.app as app_module


def test_readiness_needs_a_matching_live_worker(client):
    from extrio.runtime_health import WorkerHeartbeat

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
    heartbeat = WorkerHeartbeat(app_module.store, app_module.app.state.deployment_digest)
    heartbeat.pulse()
    assert client.get("/readyz").status_code == 200
    heartbeat.stop()
    assert client.get("/readyz").status_code == 503


def test_wrong_deployment_and_stale_worker_are_not_ready(client):
    from extrio.runtime_health import WorkerHeartbeat

    heartbeat = WorkerHeartbeat(app_module.store, "different-code-or-paths")
    heartbeat.pulse()
    assert client.get("/readyz").status_code == 503
    diagnostics = client.get("/api/v1/runtime").json()
    assert diagnostics["reason"] == "worker_deployment_mismatch"
    assert "/Users/" not in str(diagnostics)
    heartbeat.stop()
    heartbeat = WorkerHeartbeat(app_module.store, app_module.app.state.deployment_digest)
    heartbeat.pulse()
    with app_module.store.transaction() as connection:
        connection.execute("UPDATE worker_instances SET last_seen=?", ("2000-01-01T00:00:00Z",))
    assert client.get("/api/v1/runtime").json()["reason"] == "worker_unavailable"


def test_deployment_fingerprint_includes_shared_runtime_configuration(tmp_path):
    from extrio.runtime_health import deployment_digest

    settings = app_module.settings
    digest = deployment_digest(settings)
    assert deployment_digest(settings.model_copy(update={"port": settings.port + 1})) == digest
    assert deployment_digest(settings.model_copy(update={"artifact_path": tmp_path})) != digest
    assert deployment_digest(settings.model_copy(update={"signing_key_id": "other-key"})) != digest


def test_diagnostics_include_bounded_worker_identity_and_queue_age(client):
    from extrio.runtime_health import WorkerHeartbeat
    heartbeat = WorkerHeartbeat(app_module.store, app_module.app.state.deployment_digest)
    heartbeat.pulse()
    state = client.get("/api/v1/runtime").json()
    assert state["workers"][0]["id"] == heartbeat.id
    assert state["queue"] == {"queuedJobs": 0, "runningJobs": 0, "oldestDueSeconds": 0}


def test_readiness_checks_key_material_after_worker_is_live(client, tmp_path, monkeypatch):
    from extrio.integrity import LocalEd25519Signer
    from extrio.runtime_health import WorkerHeartbeat
    path = tmp_path / "missing.pem"
    signer = LocalEd25519Signer(path, app_module.settings.signing_key_id)
    app_module.store.ensure_signing_key(signer.trust_record(tenant_id=app_module.settings.tenant_id, revision=1))
    path.unlink()
    monkeypatch.setattr(app_module, "settings", app_module.settings.model_copy(update={"signing_private_key_path": path}))
    WorkerHeartbeat(app_module.store, app_module.app.state.deployment_digest).pulse()
    assert client.get("/readyz").status_code == 503
    assert client.get("/api/v1/runtime").json()["reason"] == "signing_key_unavailable"
    assert not path.exists()


def test_runtime_queue_counts_claimed_jobs_as_running(client):
    from test_job_recovery import prepared_run
    prepared_run(client)
    state = client.get("/api/v1/runtime").json()
    assert state["queue"]["runningJobs"] == 1
