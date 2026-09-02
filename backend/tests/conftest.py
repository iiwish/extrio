import os

# Existing control-plane tests exercise endpoint behavior independently from the
# authentication boundary. Dedicated authentication tests enable it explicitly.
os.environ.setdefault("EXTRIO_AUTH_ENABLED", "false")
