#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VARIANT="${1:?baseline, llvm or headless required}"
OUT="${2:?receipt directory required}"
case "$VARIANT" in baseline|llvm|headless) ;; *) exit 2 ;; esac
PROJECT="extrio-image-slim-${VARIANT}-$(date +%s)-$$"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
if [[ -n "$(docker ps -aq --filter "label=extrio.image-slim=$PROJECT")" ]] || \
   [[ -n "$(docker network ls -q --filter "label=extrio.image-slim=$PROJECT")" ]]; then
  printf 'Refusing to adopt existing test resources\n' >&2
  exit 1
fi
PG_ID=""
TEST_ID=""
NETWORK_ID=""
cleanup() {
  local result=$?
  if [[ -n "$TEST_ID" ]]; then
    docker cp "$TEST_ID:/tmp/image-tests.xml" "$OUT/tests.xml" || true
    if [[ "$(docker inspect --format '{{index .Config.Labels "extrio.image-slim"}}' "$TEST_ID")" == "$PROJECT" ]]; then
      docker rm -f "$TEST_ID"
    fi
  fi
  if [[ -n "$PG_ID" ]] && [[ "$(docker inspect --format '{{index .Config.Labels "extrio.image-slim"}}' "$PG_ID")" == "$PROJECT" ]]; then
    docker rm -fv "$PG_ID"
  fi
  if [[ -n "$NETWORK_ID" ]] && [[ "$(docker network inspect --format '{{index .Labels "extrio.image-slim"}}' "$NETWORK_ID")" == "$PROJECT" ]]; then
    docker network rm "$NETWORK_ID"
  fi
  return "$result"
}
trap cleanup EXIT

docker build -f "$ROOT/docker/backend-slim.Dockerfile" --target runtime \
  --build-arg "PRUNE_VARIANT=$VARIANT" -t "extrio/backend:slim-$VARIANT" "$ROOT"
docker build -f "$ROOT/docker/backend-slim.Dockerfile" --target verification \
  --build-arg "PRUNE_VARIANT=$VARIANT" -t "extrio/backend:slim-$VARIANT-tests" "$ROOT"
docker run --rm --network none \
  --mount "type=bind,source=$ROOT/scripts/inspect-image-security.py,target=/tmp/inspect-image-security.py,readonly" \
  --entrypoint /opt/extrio/bin/python "extrio/backend:slim-$VARIANT" \
  /tmp/inspect-image-security.py > "$OUT/runtime.json"
docker image inspect "extrio/backend:slim-$VARIANT" > "$OUT/image.json"
NETWORK_ID="$(docker network create --internal --label "extrio.image-slim=$PROJECT" "$PROJECT")"
PG_ID="$(docker run -d --network "$NETWORK_ID" --network-alias fixture-pg --label "extrio.image-slim=$PROJECT" \
  -e POSTGRES_PASSWORD=extrio_test postgres:16-alpine)"
for attempt in {1..40}; do
  if docker exec "$PG_ID" pg_isready -h 127.0.0.1 -U postgres; then break; fi
  sleep 1
done
docker exec "$PG_ID" pg_isready -h 127.0.0.1 -U postgres
TEST_ID="$(docker create --network "$NETWORK_ID" --label "extrio.image-slim=$PROJECT" \
  --mount "type=bind,source=$ROOT/backend/tests,target=/workspace/backend/tests,readonly" \
  --mount "type=bind,source=$ROOT/backend/pyproject.toml,target=/workspace/backend/pyproject.toml,readonly" \
  --mount "type=bind,source=$ROOT/docs/contracts,target=/workspace/docs/contracts,readonly" \
  --mount "type=bind,source=$ROOT/scripts,target=/workspace/scripts,readonly" \
  -w /workspace -e EXTRIO_TEST_DATABASE_URL=postgresql://postgres:extrio_test@fixture-pg:5432/postgres \
  --entrypoint /opt/extrio/bin/python "extrio/backend:slim-$VARIANT-tests" \
  -m pytest -c backend/pyproject.toml -p no:cacheprovider --junitxml=/tmp/image-tests.xml \
  backend/tests/test_runtime.py backend/tests/test_source_network.py backend/tests/test_browser_failures.py \
  backend/tests/test_official_documents.py backend/tests/test_official_v2.py backend/tests/test_source_samples.py \
  backend/tests/test_public_pagination.py \
  backend/tests/test_pagination_navigation.py backend/tests/test_nltk_boundary.py \
  backend/tests/test_lxml_boundary.py backend/tests/test_full_backup.py backend/tests/test_store_pg.py \
  backend/tests/test_tender_source_adapters.py backend/tests/test_benchmark.py)"
docker start -a "$TEST_ID"
