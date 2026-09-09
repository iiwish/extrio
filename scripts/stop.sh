#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/backend/data/pids"

stop_tree() {
  local pid="$1"
  local child
  while read -r child; do
    [[ -n "$child" ]] && stop_tree "$child"
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill "$pid" 2>/dev/null || true
}

for name in web worker api; do
  pid_file="$PID_DIR/$name.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if [[ "$pid" =~ ^[1-9][0-9]*$ ]] \
      && kill -0 "$pid" 2>/dev/null \
      && ps -p "$pid" -o command= | grep -Fq "$ROOT"; then
      stop_tree "$pid"
      printf 'stopped %s (pid %s)\n' "$name" "$pid"
    fi
    rm -f "$pid_file"
  fi
done
