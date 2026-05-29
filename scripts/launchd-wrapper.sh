#!/bin/bash
# launchd entry point: runs the daemon in the foreground so launchd can
# supervise it (KeepAlive restarts it on crash).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
exec python3 -m net_auto_switch.cli --config "$PROJECT_DIR/config.toml"
