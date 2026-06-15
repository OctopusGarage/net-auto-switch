#!/bin/bash
# Install the project git hooks (symlink, so updates to scripts/pre-commit take
# effect automatically). Run once after cloning: ./scripts/install-hooks.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOK_DIR="$PROJECT_ROOT/.git/hooks"

if [ ! -d "$HOOK_DIR" ]; then
  echo "[install-hooks] ✗ $HOOK_DIR not found — run this inside the git repo."
  exit 1
fi

chmod +x "$SCRIPT_DIR/pre-commit"
ln -sf "../../scripts/pre-commit" "$HOOK_DIR/pre-commit"
echo "[install-hooks] ✓ linked .git/hooks/pre-commit -> scripts/pre-commit"
echo "[install-hooks]   it runs ruff check / format --check / pytest / secret scan."
echo "[install-hooks]   bypass once with: git commit --no-verify"
