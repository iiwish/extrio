#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${EXTRIO_E2E_PROJECT:-extrio-e2e}"
export EXTRIO_API_PORT="${EXTRIO_API_PORT:-18000}"
export EXTRIO_WEB_PORT="${EXTRIO_WEB_PORT:-18080}"
export EXTRIO_BACKEND_IMAGE="${EXTRIO_BACKEND_IMAGE:-extrio/backend:e2e}"
export EXTRIO_WEB_IMAGE="${EXTRIO_WEB_IMAGE:-extrio/web:e2e}"
export EXTRIO_CORS_ORIGINS="http://127.0.0.1:${EXTRIO_WEB_PORT},http://localhost:${EXTRIO_WEB_PORT}"

COOKIE_JAR="$(mktemp)"
cleanup() {
  rm -f "$COOKIE_JAR"
  docker compose -p "$PROJECT" -f "$ROOT/compose.yaml" down -v --remove-orphans
}
trap cleanup EXIT

docker compose -p "$PROJECT" -f "$ROOT/compose.yaml" up --build --wait --detach

api="http://127.0.0.1:${EXTRIO_API_PORT}/api/v1"
web="http://127.0.0.1:${EXTRIO_WEB_PORT}"

test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$api/collectors")" = "401"
curl --fail --silent "$api/auth/state" | grep -q '"setupRequired":true'
curl --fail --silent --cookie-jar "$COOKIE_JAR" \
  --header 'Content-Type: application/json' \
  --data '{"username":"release-admin","displayName":"Release Operator","password":"release-verification-password"}' \
  "$api/auth/setup" | grep -q '"authenticated":true'
curl --fail --silent --cookie "$COOKIE_JAR" "$api/collectors" | grep -q '"items"'
curl --fail --silent "$web/" | grep -q '<title>Extrio'
curl --fail --silent --cookie "$COOKIE_JAR" --request POST "$api/auth/logout" | grep -q '"authenticated":false'
test "$(curl --silent --output /dev/null --write-out '%{http_code}' --cookie "$COOKIE_JAR" "$api/collectors")" = "401"

docker compose -p "$PROJECT" -f "$ROOT/compose.yaml" ps
printf 'Docker authenticated end-to-end verification passed at %s\n' "$web"
