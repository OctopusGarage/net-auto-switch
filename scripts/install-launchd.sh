#!/bin/bash
# Install net-auto-switch as a launchd agent (auto-start on boot, restart on crash).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.octopusgarage.net-auto-switch.plist"
LABEL="com.octopusgarage.net-auto-switch"
TARGET="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "[install-launchd] Installing dependencies..."
python3 -m pip install -e "$PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/config.toml" ]; then
  echo "[install-launchd] Creating config.toml from example — edit it before relying on it."
  cp "$PROJECT_DIR/config.example.toml" "$PROJECT_DIR/config.toml"
fi

mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$HOME/Library/LaunchAgents"

sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$SCRIPT_DIR/net-auto-switch.plist" > "$TARGET"
echo "[install-launchd] Installed to $TARGET"

if launchctl list "$LABEL" >/dev/null 2>&1; then
  echo "[install-launchd] Unloading old service..."
  launchctl unload "$TARGET" 2>/dev/null || true
fi

echo "[install-launchd] Loading service..."
launchctl load "$TARGET"

echo "[install-launchd] Done. Inspect with:"
echo "  launchctl list $LABEL"
echo "  tail -f $PROJECT_DIR/logs/launchd.err.log"
