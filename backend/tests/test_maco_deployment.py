import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_public_demo_keeps_runtime_authenticated_and_private():
    manifest = json.loads((ROOT / "deploy/maco.json").read_text())
    compose = yaml.safe_load((ROOT / "deploy/compose.maco.yaml").read_text())
    assert manifest["ingress"]["hostname"] == "extrio-app.ouvo.ai"
    assert manifest["ingress"]["authorization_ref"]
    for service in ("api", "worker"):
        config = compose["services"][service]
        assert not config.get("ports")
        assert config["environment"]["EXTRIO_AUTH_ENABLED"] == "true"
        assert config["environment"]["EXTRIO_AUTH_COOKIE_SECURE"] == "true"
        assert config["environment"]["EXTRIO_DATABASE_AUTO_MIGRATE"] == "false"
        assert "https://extrio-app.ouvo.ai" in config["environment"]["EXTRIO_CORS_ORIGINS"].split(",")
    assert compose["services"]["web"]["ports"] == ["127.0.0.1:18085:8080"]


def test_public_proxy_requires_https_and_blocks_bootstrap():
    config = (ROOT / "deploy/openresty.extrio.conf").read_text()
    assert "server_name extrio-app.ouvo.ai;" in config
    assert "return 308 https://extrio-app.ouvo.ai$request_uri;" in config
    assert "location ^~ /api/v1/auth/setup {\n        return 403;" in config
    assert "if (-f /www/extrio-demo.pending)" in config
    assert "proxy_pass http://127.0.0.1:18085;" in config
    assert "deny all;" in config
    assert "proxy_cache off;" in config
