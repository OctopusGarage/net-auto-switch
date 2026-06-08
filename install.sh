#!/bin/bash
# One-line installer for net-auto-switch.
#
#   curl -fsSL https://raw.githubusercontent.com/OctopusGarage/net-auto-switch/main/install.sh | bash
#
# Installs uv (if missing), clones the repo to ~/.net-auto-switch (override with
# NET_AUTO_SWITCH_DIR), syncs deps, drops a global `net-auto-switch` launcher,
# and runs the guided `init` wizard. Re-running it updates an existing install.
set -euo pipefail

REPO="https://github.com/OctopusGarage/net-auto-switch.git"
INSTALL_DIR="${NET_AUTO_SWITCH_DIR:-$HOME/.net-auto-switch}"
BIN_DIR="$HOME/.local/bin"

info() { printf '\033[1;34m=>\033[0m %s\n' "$*"; }
err() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; }

[ "$(uname)" = "Darwin" ] || {
  err "net-auto-switch is macOS-only."
  exit 1
}
command -v git >/dev/null 2>&1 || {
  err "git not found - install the Xcode Command Line Tools: xcode-select --install"
  exit 1
}

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$BIN_DIR:$PATH"
fi
command -v uv >/dev/null 2>&1 || {
  err "uv install failed - see https://docs.astral.sh/uv/"
  exit 1
}

# 2. clone or update (in place; never deletes - config.toml is gitignored/preserved)
if [ -d "$INSTALL_DIR/.git" ]; then
  info "Found existing install at $INSTALL_DIR, updating..."
  if ! git -C "$INSTALL_DIR" pull --ff-only; then
    err "Couldn't fast-forward $INSTALL_DIR (local changes to tracked files, or"
    err "diverged history). Your config.toml is untracked and will be preserved."
    err "Reset it to the latest and re-run this installer:"
    err "  git -C \"$INSTALL_DIR\" fetch origin && git -C \"$INSTALL_DIR\" reset --hard origin/main"
    exit 1
  fi
else
  info "Cloning into $INSTALL_DIR..."
  git clone "$REPO" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# 3. dependencies
info "Syncing dependencies..."
uv sync

# 4. global launcher, so `net-auto-switch ...` works from anywhere
info "Installing launcher to $BIN_DIR/net-auto-switch..."
mkdir -p "$BIN_DIR"
cat >"$BIN_DIR/net-auto-switch" <<EOF
#!/bin/bash
exec uv run --project "$INSTALL_DIR" net-auto-switch "\$@"
EOF
chmod +x "$BIN_DIR/net-auto-switch"

# 5. guided setup - read prompts from the terminal even when piped via curl
info "Starting guided setup..."
if [ -e /dev/tty ]; then
  "$BIN_DIR/net-auto-switch" init </dev/tty
else
  "$BIN_DIR/net-auto-switch" init --yes
fi

info "Done. Installed at $INSTALL_DIR"
info "Update later with:  net-auto-switch update"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) info "Add $BIN_DIR to your PATH to use the 'net-auto-switch' command." ;;
esac
