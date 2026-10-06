import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "docker/backend.Dockerfile"


def test_backend_image_pins_a_supported_debian_generation_and_matching_pg_repository():
    source = DOCKERFILE.read_text()
    assert re.search(r"^FROM ghcr\.io/astral-sh/uv:python3\.12-trixie-slim@sha256:[0-9a-f]{64}$", source, re.MULTILINE)
    assert "trixie-pgdg main" in source
    assert "bookworm" not in source
    assert "postgresql-client-16" in source
    assert "uv sync --project backend --frozen --no-dev" in source


def test_backend_image_removes_setup_tools_without_removing_the_browser_runtime():
    source = DOCKERFILE.read_text()
    setup = source.index("playwright install --with-deps chromium")
    purge = source.index("apt-get purge -y curl xvfb xserver-common")
    user = source.index("USER extrio")
    assert setup < purge < user
    assert "chmod -R a+rX /ms-playwright" in source
    assert "uv pip uninstall --system --python /usr/local/bin/python pip" in source
    assert "apt-get autoremove" not in source
