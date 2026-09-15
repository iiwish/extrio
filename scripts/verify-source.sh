#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTANCE="$(mktemp -d "${TMPDIR:-/tmp}/extrio-source-check.XXXXXX")"
export EXTRIO_INSTANCE_DIR="$INSTANCE"
export EXTRIO_API_PORT="${EXTRIO_API_PORT:-18100}"
export EXTRIO_WEB_PORT="${EXTRIO_WEB_PORT:-15173}"
export EXTRIO_AUTH_ENABLED=true

# Never let inherited deployment storage or keys escape the disposable instance.
unset EXTRIO_DATABASE_URL EXTRIO_DATABASE_PATH EXTRIO_ARTIFACT_PATH
unset EXTRIO_SIGNING_PRIVATE_KEY_PATH EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH

cleanup() {
  local result=$?
  "$ROOT/scripts/stop.sh"
  if (( result == 0 )); then
    rm -rf "$INSTANCE"
  else
    printf 'Verification logs retained at %s\n' "$INSTANCE/logs" >&2
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$ROOT/scripts/dev.sh"
curl --fail --silent "http://127.0.0.1:$EXTRIO_API_PORT/readyz" | grep -q '"ready":true'
curl --fail --silent "http://127.0.0.1:$EXTRIO_API_PORT/api/v1/auth/state" | grep -q '"setupRequired":true'
test "$(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:$EXTRIO_API_PORT/api/v1/collectors")" = "401"
curl --fail --silent "http://127.0.0.1:$EXTRIO_WEB_PORT/" | grep -q '<title>Extrio'
printf 'Disposable source startup, Worker readiness and authentication boundary passed.\n'
