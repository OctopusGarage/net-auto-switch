#!/bin/bash
# One-line installer for net-auto-switch.
#
#   curl -fsSL https://raw.githubusercontent.com/OctopusGarage/net-auto-switch/main/install.sh | bash
#
# Installs uv (if missing), downloads the latest release tarball to
# ~/.net-auto-switch (override with NET_AUTO_SWITCH_DIR), syncs deps, drops a
# global `net-auto-switch` launcher, and runs the guided `init` wizard.
# Re-running it updates an existing install. Pin a version with
# NET_AUTO_SWITCH_VERSION=v0.3.3.
set -euo pipefail

REPO="OctopusGarage/net-auto-switch"
INSTALL_DIR="${NET_AUTO_SWITCH_DIR:-$HOME/.net-auto-switch}"
BIN_DIR="$HOME/.local/bin"
VERSION="${NET_AUTO_SWITCH_VERSION:-latest}"

info() { printf '\033[1;34m=>\033[0m %s\n' "$*"; }
err() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; }

[ "$(uname)" = "Darwin" ] || {
  err "net-auto-switch is macOS-only."
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

# 2. resolve the release tag (follow the /releases/latest redirect; no jq needed)
if [ "$VERSION" = "latest" ]; then
  url=$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
    "https://github.com/$REPO/releases/latest") || {
    err "Couldn't reach GitHub to resolve the latest release."
    exit 1
  }
  TAG="${url##*/}"
else
  TAG="$VERSION"
fi
case "$TAG" in
  v*) ;;
  *) err "Couldn't resolve a release tag (got '$TAG')."; exit 1 ;;
esac

# 3. download + extract the filtered release tarball into INSTALL_DIR.
#    config.toml is gitignored, so it's absent from the archive and preserved.
info "Downloading $TAG..."
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://github.com/$REPO/archive/refs/tags/${TAG}.tar.gz" -o "$tmp/release.tar.gz" || {
  err "Download failed for $TAG."
  exit 1
}
# Migrate a previous git-clone install: drop its VCS metadata, keep .venv/config.toml.
[ -d "$INSTALL_DIR/.git" ] && rm -rf "$INSTALL_DIR/.git"
mkdir -p "$INSTALL_DIR"
tar -xzf "$tmp/release.tar.gz" --strip-components=1 -C "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 4. dependencies
info "Syncing dependencies..."
uv sync

# 5. global launcher, so `net-auto-switch ...` works from anywhere
info "Installing launcher to $BIN_DIR/net-auto-switch..."
mkdir -p "$BIN_DIR"
cat >"$BIN_DIR/net-auto-switch" <<EOF
#!/bin/bash
exec uv run --project "$INSTALL_DIR" net-auto-switch "\$@"
EOF
chmod +x "$BIN_DIR/net-auto-switch"

# 6. guided setup - read prompts from the terminal even when piped via curl
info "Starting guided setup..."
if [ -e /dev/tty ]; then
  "$BIN_DIR/net-auto-switch" init </dev/tty
else
  "$BIN_DIR/net-auto-switch" init --yes
fi

info "Done. Installed $TAG at $INSTALL_DIR"
info "Update later with:  net-auto-switch update"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) info "Add $BIN_DIR to your PATH to use the 'net-auto-switch' command." ;;
esac
