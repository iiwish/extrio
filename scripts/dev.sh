#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/backend/data/logs"
PID_DIR="$ROOT/backend/data/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

start_process() {
  local name="$1"
  shift
  local pid_file="$PID_DIR/$name.pid"
  if [[ -f "$pid_file" ]]; then
    local existing_pid
    existing_pid="$(cat "$pid_file")"
    if [[ -n "$existing_pid" ]] \
      && kill -0 "$existing_pid" 2>/dev/null \
      && ps -p "$existing_pid" -o command= | grep -Fq "$ROOT"; then
      printf '%s already running (pid %s)\n' "$name" "$existing_pid"
      return
    fi
    rm -f "$pid_file"
  fi
  nohup "$@" >"$LOG_DIR/$name.log" 2>&1 </dev/null &
  echo "$!" >"$pid_file"
  printf 'started %s (pid %s)\n' "$name" "$!"
}

start_process api env EXTRIO_ALLOW_HTTP_LOCALHOST=true EXTRIO_ALLOW_HTTP_PUBLIC=true uv run --project "$ROOT/backend" extrio-api
start_process worker env EXTRIO_ALLOW_HTTP_LOCALHOST=true EXTRIO_ALLOW_HTTP_PUBLIC=true uv run --project "$ROOT/backend" extrio-worker
start_process web pnpm --dir "$ROOT/web" dev --host 127.0.0.1

printf '\nExtrio: http://127.0.0.1:5173\nAPI:    http://127.0.0.1:8000/docs\nLogs:   %s\n' "$LOG_DIR"
