import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "docker/backend.Dockerfile"


def test_backend_image_pins_qualified_ubuntu_and_matching_pg_repository():
    source = DOCKERFILE.read_text()
    assert re.search(r"^FROM ubuntu:24\.04@sha256:[0-9a-f]{64} AS runtime$", source, re.MULTILINE)
    assert "noble-pgdg main" in source
    assert "trixie" not in source and "resolute" not in source
    assert "postgresql-client-16" in source
    assert "uv sync --project backend --python /usr/bin/python3.12 --frozen --no-dev" in source
    assert "UV_PYTHON_PREFERENCE=only-system" in source
    assert source.rstrip().endswith("FROM runtime AS default")


def test_backend_image_removes_setup_tools_without_removing_the_browser_runtime():
    source = DOCKERFILE.read_text()
    setup = source.index("playwright install --with-deps --only-shell chromium")
    purge = source.index("apt-get purge -y curl xvfb xserver-common")
    user = source.index("USER extrio")
    assert setup < purge < user
    assert "chmod -R a+rX /ms-playwright" in source
    assert "prune-image-runtime.py only-shell" in source
    assert "--break-system-packages" not in source
    assert "apt-get autoremove" not in source


def test_historical_debian_control_is_not_the_default_build():
    root = DOCKERFILE.parents[1]
    source = (root / "docker/backend-debian-control.Dockerfile").read_text()
    assert "python3.12-trixie-slim@sha256:" in source
    for name in ("image-base.yml", "image-slim.yml"):
        workflow = (root / ".github/workflows" / name).read_text()
        assert "-f docker/backend-debian-control.Dockerfile" in workflow
    harness = (root / "scripts/verify-slim-image.sh").read_text()
    assert "noble) DOCKERFILE=backend.Dockerfile" in harness
