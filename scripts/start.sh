#!/bin/bash
# Start net-auto-switch in the background (manual run, NOT launchd).
# For boot auto-start, use install-launchd.sh instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_ROOT/.net-auto-switch.pid"
PROC_PATTERN="net_auto_switch.cli"

if pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; then
  echo "[start] Already running (pid $(pgrep -f "$PROC_PATTERN" | head -1)). Run scripts/stop.sh first."
  exit 1
fi

if [ ! -f "$PROJECT_ROOT/config.toml" ]; then
  echo "[start] Missing config.toml. Copy config.example.toml to config.toml and edit it."
  exit 1
fi

mkdir -p "$PROJECT_ROOT/logs"
cd "$PROJECT_ROOT"
nohup python3 -m net_auto_switch.cli --config "$PROJECT_ROOT/config.toml" \
  >> "$PROJECT_ROOT/logs/net-auto-switch.out.log" 2>&1 &
echo $! > "$PID_FILE"
echo "[start] Started (pid $(cat "$PID_FILE")). Logs: logs/net-auto-switch.out.log"
