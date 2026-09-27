#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${EXTRIO_E2E_PROJECT:-extrio-e2e-$(date +%Y%m%d%H%M%S)-$$}"
COMPOSE_FILE="${EXTRIO_E2E_COMPOSE_FILE:-$ROOT/compose.yaml}"
UP_OPTIONS=(--build)
if (( $# > 0 )); then
  if (( $# != 1 )) || [[ "$1" != "--image-only" ]]; then
    printf 'Usage: %s [--image-only]\n' "$0" >&2
    exit 1
  fi
  for variable in EXTRIO_BACKEND_IMAGE EXTRIO_WEB_IMAGE; do
    if [[ ! "${!variable:-}" =~ ^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$ ]]; then
      printf '%s must be an explicit digest-pinned image (repository@sha256:<64 lowercase hex digits>)\n' "$variable" >&2
      exit 1
    fi
  done
  # Only these profiles guarantee all application services use the validated image variables.
  COMPOSE_FILE="$(cd "$(dirname "$COMPOSE_FILE")" && pwd)/$(basename "$COMPOSE_FILE")"
  if [[ "$COMPOSE_FILE" != "$ROOT/compose.yaml" && "$COMPOSE_FILE" != "$ROOT/compose.postgres.yaml" ]]; then
    printf 'Image-only verification requires the repository compose.yaml or compose.postgres.yaml\n' >&2
    exit 1
  fi
  UP_OPTIONS=(--no-build --pull always)
  printf 'Image-only verification: backend=%s web=%s\n' "$EXTRIO_BACKEND_IMAGE" "$EXTRIO_WEB_IMAGE"
fi
if [[ ! "$PROJECT" =~ ^extrio-e2e- ]]; then
  printf 'Use a unique disposable EXTRIO_E2E_PROJECT beginning extrio-e2e-\n' >&2
  exit 1
fi
if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] || [[ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  printf 'Refusing to adopt an existing project or its volumes\n' >&2
  exit 1
fi
export EXTRIO_API_PORT="${EXTRIO_API_PORT:-18000}"
export EXTRIO_WEB_PORT="${EXTRIO_WEB_PORT:-18080}"
export EXTRIO_BACKEND_IMAGE="${EXTRIO_BACKEND_IMAGE:-extrio/backend:e2e}"
export EXTRIO_WEB_IMAGE="${EXTRIO_WEB_IMAGE:-extrio/web:e2e}"
export EXTRIO_CORS_ORIGINS="http://127.0.0.1:${EXTRIO_WEB_PORT},http://localhost:${EXTRIO_WEB_PORT}"

COOKIE_JAR="$(mktemp)"
cleanup() {
  local result=$?
  if (( result != 0 )); then
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" logs --tail 80 || true
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps -q | xargs -r docker inspect --format '{{.Name}} {{json .State.Health}}' || true
  fi
  rm -f "$COOKIE_JAR"
  docker compose -p "$PROJECT" -f "$COMPOSE_FILE" down -v --remove-orphans
}
trap cleanup EXIT

docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up "${UP_OPTIONS[@]}" --wait --wait-timeout 180 --detach

api="http://127.0.0.1:${EXTRIO_API_PORT}/api/v1"
web="http://127.0.0.1:${EXTRIO_WEB_PORT}"
curl --fail --silent "http://127.0.0.1:${EXTRIO_API_PORT}/readyz" | grep -q '"ready":true'

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

docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps
printf 'Docker authenticated end-to-end verification passed at %s\n' "$web"
