#!/bin/bash
# Show whether net-auto-switch is running.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROC_PATTERN="net_auto_switch.cli"

PID="$(pgrep -f "$PROC_PATTERN" | head -1 || true)"
if [ -z "$PID" ]; then
  echo "[status] Not running."
  exit 1
fi

echo "[status] Running. PID: $PID"
echo "[status] Uptime:"
ps -p "$PID" -o etime=
