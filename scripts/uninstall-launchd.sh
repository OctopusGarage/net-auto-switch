#!/bin/bash
# Unload and remove the net-auto-switch launchd agent.
set -euo pipefail

PLIST_NAME="com.octopusgarage.net-auto-switch.plist"
TARGET="$HOME/Library/LaunchAgents/$PLIST_NAME"

if [ -f "$TARGET" ]; then
  launchctl unload "$TARGET" 2>/dev/null || true
  rm -f "$TARGET"
  echo "[uninstall-launchd] Removed $TARGET"
else
  echo "[uninstall-launchd] No agent installed at $TARGET"
fi
