#!/bin/bash
# launchd entry point: runs the daemon in the foreground so launchd can
# supervise it (KeepAlive restarts it on crash).
#
# Uses the uv-managed venv interpreter (absolute path) so it does NOT depend on
# whatever python3 happens to be on launchd's PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
exec "$PROJECT_DIR/.venv/bin/python" -m net_auto_switch.cli --config "$PROJECT_DIR/config.toml"
