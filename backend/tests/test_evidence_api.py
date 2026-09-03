"""Evidence-bundle HTTP endpoint tests (v0.5).

Covers the 200 ZIP roundtrip verified against the store's registered public
key, the query scope pass-through, the 404 collector mapping, and the
EVIDENCE_BUNDLE_ERROR mapping for unbuildable scopes.
"""

from pathlib import Path

from fastapi.testclient import TestClient

import extrio.app as app_module
from extrio.evidence import verify_evidence_bundle
from extrio.store import Store


def make_store(tmp_path: Path, name: str) -> Store:
    store = Store(tmp_path / f"{name}.db")
    store.initialize()
    return store


def store_public_key_pem(store: Store) -> str:
    store.ensure_signing_key(app_module.rule_signer.trust_record(tenant_id=app_module.settings.tenant_id, revision=1))
    signing_key = store.get_signing_key(app_module.rule_signer.key_id)
    assert signing_key is not None
    return str(signing_key["publicKeyPem"])


def test_evidence_bundle_endpoint_streams_verifiable_zip(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path, "evidence-api")
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")

            response = client.get(f"/api/v1/collectors/{collector['id']}/evidence-bundle")

            assert response.status_code == 200, response.json()
            assert response.headers["Content-Type"] == "application/zip"
            assert response.headers["Content-Disposition"] == f'attachment; filename="extrio-evidence-{collector["id"]}.zip"'
            result = verify_evidence_bundle(response.content, public_key_pem=store_public_key_pem(app_module.store))
            assert result["valid"] is True, result["errors"]
            assert result["summary"] == {"runs": 0, "items": 0, "deliveries": 0}
    finally:
        app_module.store = original


def test_evidence_bundle_endpoint_accepts_scope_parameters(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path, "evidence-api-scope")
    try:
        with TestClient(app_module.app) as client:
            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")

            response = client.get(
                f"/api/v1/collectors/{collector['id']}/evidence-bundle",
                params={"since": "2026-08-01T00:00:00Z", "until": "2026-09-01T00:00:00Z"},
            )

            assert response.status_code == 200, response.json()
            result = verify_evidence_bundle(response.content, public_key_pem=store_public_key_pem(app_module.store))
            assert result["valid"] is True, result["errors"]
    finally:
        app_module.store = original


def test_evidence_bundle_endpoint_maps_collector_and_bundle_errors(tmp_path: Path) -> None:
    original = app_module.store
    app_module.store = make_store(tmp_path, "evidence-api-errors")
    try:
        with TestClient(app_module.app) as client:
            missing = client.get("/api/v1/collectors/collector_missing/evidence-bundle")
            assert missing.status_code == 404
            assert missing.json()["code"] == "COLLECTOR_NOT_FOUND"

            collector = app_module.store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
            unknown_rule = client.get(
                f"/api/v1/collectors/{collector['id']}/evidence-bundle",
                params={"ruleVersionId": "rule_unknown_v1"},
            )
            assert unknown_rule.status_code == 400
            assert unknown_rule.json()["code"] == "EVIDENCE_BUNDLE_ERROR"
            assert "rule_unknown_v1" in unknown_rule.json()["message"]
    finally:
        app_module.store = original
