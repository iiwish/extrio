#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTANCE_DIR="${EXTRIO_INSTANCE_DIR:-$ROOT/backend/data}"
LOG_DIR="$INSTANCE_DIR/logs"
PID_DIR="$INSTANCE_DIR/pids"
API_PORT="${EXTRIO_API_PORT:-${EXTRIO_PORT:-8000}}"
WEB_PORT="${EXTRIO_WEB_PORT:-5173}"
export EXTRIO_PORT="$API_PORT"
export EXTRIO_HOST=127.0.0.1
export EXTRIO_DATABASE_PATH="${EXTRIO_DATABASE_PATH:-$INSTANCE_DIR/extrio.db}"
export EXTRIO_ARTIFACT_PATH="${EXTRIO_ARTIFACT_PATH:-$INSTANCE_DIR/artifacts}"
export EXTRIO_SIGNING_PRIVATE_KEY_PATH="${EXTRIO_SIGNING_PRIVATE_KEY_PATH:-$INSTANCE_DIR/keys/dev-rule-signing-key.pem}"
export EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH="${EXTRIO_CREDENTIAL_ENCRYPTION_KEY_PATH:-$INSTANCE_DIR/keys/dev-credential-encryption.key}"
export EXTRIO_CORS_ORIGINS="${EXTRIO_CORS_ORIGINS:-http://127.0.0.1:$WEB_PORT,http://localhost:$WEB_PORT}"
export EXTRIO_API_PROXY_TARGET="http://127.0.0.1:$API_PORT"
mkdir -p "$LOG_DIR" "$PID_DIR"

managed_process() {
  local file="$PID_DIR/$1.pid" pid
  [[ -f "$file" ]] || return 1
  pid="$(cat "$file")"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o command= | grep -Fq "$ROOT"
}

check_ports=()
if ! managed_process api; then check_ports+=("$API_PORT"); fi
if ! managed_process web; then check_ports+=("$WEB_PORT"); fi
if (( ${#check_ports[@]} > 0 )); then
uv run --project "$ROOT/backend" python -c '
import socket, sys
ports = [int(value) for value in sys.argv[1:]]
if len(set(ports)) != len(ports):
    raise SystemExit("Port conflict: API and web require distinct ports")
for port in ports:
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    except (OSError, OverflowError):
        raise SystemExit(f"Port conflict at 127.0.0.1:{port}; select another port before startup")
' "${check_ports[@]}"
fi

started=()
stop_tree() {
  local child
  while read -r child; do [[ -n "$child" ]] && stop_tree "$child"; done < <(pgrep -P "$1" 2>/dev/null || true)
  kill "$1" 2>/dev/null || true
}
cleanup_failed() {
  local status=$? entry name pid
  if [[ "$status" != 0 ]]; then
    for entry in "${started[@]}"; do
      name="${entry%%:*}"; pid="${entry##*:}"
      stop_tree "$pid"
      rm -f "$PID_DIR/$name.pid"
    done
  fi
}
trap cleanup_failed EXIT

start_process() {
  local name="$1"
  shift
  local pid_file="$PID_DIR/$name.pid"
  if [[ -f "$pid_file" ]]; then
    local existing_pid
    existing_pid="$(cat "$pid_file")"
    if [[ "$existing_pid" =~ ^[1-9][0-9]*$ ]] \
      && kill -0 "$existing_pid" 2>/dev/null \
      && ps -p "$existing_pid" -o command= | grep -Fq "$ROOT"; then
      printf '%s already running (pid %s)\n' "$name" "$existing_pid"
      return
    fi
    rm -f "$pid_file"
  fi
  local log_file="$LOG_DIR/$name.log"
  nohup "$@" >"$log_file" 2>&1 </dev/null &
  echo "$!" >"$pid_file"
  started+=("$name:$!")
  sleep 0.5
  if ! kill -0 "$!" 2>/dev/null; then
    printf 'failed to start %s; recent log output:\n' "$name" >&2
    tail -n 20 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  printf 'started %s (pid %s)\n' "$name" "$!"
}

start_process api env EXTRIO_AUTH_ENABLED="${EXTRIO_AUTH_ENABLED:-true}" EXTRIO_ALLOW_HTTP_LOCALHOST=true EXTRIO_ALLOW_HTTP_PUBLIC=true uv run --project "$ROOT/backend" extrio-api
start_process worker env EXTRIO_ALLOW_HTTP_LOCALHOST=true EXTRIO_ALLOW_HTTP_PUBLIC=true uv run --project "$ROOT/backend" extrio-worker
start_process web pnpm --dir "$ROOT/web" dev --host 127.0.0.1 --port "$WEB_PORT" --strictPort

ready=false
for _ in {1..60}; do
  if curl --fail --silent "http://127.0.0.1:$API_PORT/readyz" >/dev/null; then ready=true; break; fi
  if ! managed_process api || ! managed_process worker || ! managed_process web; then break; fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  printf 'Instance did not become ready; inspect %s and run extrio-doctor\n' "$LOG_DIR" >&2
  exit 1
fi
printf '\nExtrio: http://127.0.0.1:%s\nAPI:    http://127.0.0.1:%s/docs\nLogs:   %s\n' "$WEB_PORT" "$API_PORT" "$LOG_DIR"
