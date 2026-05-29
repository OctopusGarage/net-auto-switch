#!/bin/bash
# Stop a manually-started net-auto-switch (NOT the launchd agent — use
# uninstall-launchd.sh for that).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_ROOT/.net-auto-switch.pid"
PROC_PATTERN="net_auto_switch.cli"

PID="$(pgrep -f "$PROC_PATTERN" | head -1 || true)"
if [ -z "$PID" ]; then
  echo "[stop] No running instance found."
  rm -f "$PID_FILE"
  exit 0
fi

echo "[stop] Stopping PID $PID..."
kill "$PID" 2>/dev/null || true
sleep 1
if ps -p "$PID" >/dev/null 2>&1; then
  echo "[stop] Force killing $PID..."
  kill -9 "$PID" 2>/dev/null || true
fi
rm -f "$PID_FILE"
echo "[stop] Stopped."
