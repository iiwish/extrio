import os
import tempfile
from pathlib import Path

_instance = tempfile.TemporaryDirectory(prefix="extrio-pytest-")
_root = Path(_instance.name)
for variable, relative in {
    "EXTRIO_DATABASE_PATH": "extrio.db",
    "EXTRIO_ARTIFACT_PATH": "artifacts",
    "EXTRIO_SIGNING_PRIVATE_KEY_PATH": "keys/signing.pem",
    "EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH": "keys/credentials.key",
}.items():
    os.environ[variable] = str(_root / relative)


def pytest_unconfigure(config):
    _instance.cleanup()

# Existing control-plane tests exercise endpoint behavior independently from the
# authentication boundary. Dedicated authentication tests enable it explicitly.
os.environ.setdefault("EXTRIO_AUTH_ENABLED", "false")

# Store tests must keep the zero-config SQLite profile even when a developer
# environment carries EXTRIO_DATABASE_URL. The PostgreSQL suite targets an
# explicit test server through EXTRIO_TEST_DATABASE_URL instead.
os.environ.pop("EXTRIO_DATABASE_URL", None)
