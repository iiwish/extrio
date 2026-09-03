import os

# Existing control-plane tests exercise endpoint behavior independently from the
# authentication boundary. Dedicated authentication tests enable it explicitly.
os.environ.setdefault("EXTRIO_AUTH_ENABLED", "false")

# Store tests must keep the zero-config SQLite profile even when a developer
# environment carries EXTRIO_DATABASE_URL. The PostgreSQL suite targets an
# explicit test server through EXTRIO_TEST_DATABASE_URL instead.
os.environ.pop("EXTRIO_DATABASE_URL", None)
