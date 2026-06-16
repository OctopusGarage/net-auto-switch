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

# 3. download + extract the release tarball into INSTALL_DIR.
#    Prefer the curated lean asset; fall back to the full source archive for older
#    releases that predate it. config.toml is gitignored / not in either archive,
#    so it's preserved.
info "Downloading $TAG..."
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
asset="https://github.com/$REPO/releases/download/${TAG}/net-auto-switch-${TAG}.tar.gz"
source_archive="https://github.com/$REPO/archive/refs/tags/${TAG}.tar.gz"
curl -fsSL "$asset" -o "$tmp/release.tar.gz" \
  || curl -fsSL "$source_archive" -o "$tmp/release.tar.gz" || {
    err "Download failed for $TAG."
    exit 1
  }
# Migrate a previous git-clone install: drop its VCS metadata, keep .venv/config.toml.
[ -d "$INSTALL_DIR/.git" ] && rm -rf "$INSTALL_DIR/.git"
mkdir -p "$INSTALL_DIR"
# Clean stale files from a previous (possibly bloated) install so anything dropped
# between versions doesn't linger; preserve user config, the venv, and logs. Guarded
# so we only ever prune something that already looks like an install.
if [ -d "$INSTALL_DIR/net_auto_switch" ] || [ -f "$INSTALL_DIR/pyproject.toml" ]; then
  find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 \
    ! -name config.toml ! -name config.toml.bak ! -name .venv \
    ! -name logs ! -name .net-auto-switch.pid \
    -exec rm -rf {} +
fi
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

# 5b. zsh tab-completion (macOS default shell). Idempotent: each run strips any
#     previous block and writes exactly one, so re-installing never duplicates it.
#     It points at $INSTALL_DIR/completions (refreshed in place by `update`), so
#     updates need no re-registration.
register_zsh_completion() {
  local rc="$HOME/.zshrc"
  local start="# >>> net-auto-switch completion >>>"
  local end="# <<< net-auto-switch completion <<<"
  [ -f "$INSTALL_DIR/completions/_net-auto-switch" ] || return 0
  [ -f "$rc" ] || touch "$rc"
  if grep -qF "$start" "$rc"; then
    local tmp
    tmp="$(mktemp)"
    awk -v s="$start" -v e="$end" '
      $0==s {skip=1} skip && $0==e {skip=0; next} !skip {print}
    ' "$rc" >"$tmp" && mv "$tmp" "$rc"
  fi
  {
    printf '%s\n' "$start"
    printf 'fpath=("%s/completions" $fpath)\n' "$INSTALL_DIR"
    printf 'autoload -Uz compinit && compinit\n'
    printf '%s\n' "$end"
  } >>"$rc"
}
info "Enabling zsh tab-completion..."
register_zsh_completion

# 5c. AI agent skill (optional, opt-in). Installs the net-auto-switch agent skill
#     globally via the `skills` CLI (~/.agents/skills), so AI agents like Claude
#     Code can drive the tool. Needs Node/npx; idempotent (skips if present).
SKILLS_SLUG="net-auto-switch"
install_agent_skill() {
  if ! command -v npx >/dev/null 2>&1; then
    info "Skipping agent skill: npx (Node.js) not found. Install later with: npx skills add $REPO -y -g"
    return 0
  fi
  if npx -y skills ls -g 2>/dev/null | grep -q "$SKILLS_SLUG"; then
    info "Agent skill already installed."
    return 0
  fi
  info "Installing agent skill via 'skills'..."
  if npx -y skills add "$REPO" -y -g >/dev/null 2>&1; then
    info "Agent skill installed (~/.agents/skills)."
  else
    info "Agent skill install failed. Retry later with: npx skills add $REPO -y -g"
  fi
}
if [ -e /dev/tty ]; then
  printf '> Install the AI agent skill for Claude Code / agents? [y/N] ' >/dev/tty
  read -r skill_ans </dev/tty || skill_ans=""
  case "$skill_ans" in
    [yY] | [yY][eE][sS]) install_agent_skill ;;
    *) info "Skipped agent skill. Install later with: npx skills add $REPO -y -g" ;;
  esac
else
  info "Non-interactive: skipped agent skill. Install later with: npx skills add $REPO -y -g"
fi

# 6. guided setup - read prompts from the terminal even when piped via curl
info "Starting guided setup..."
if [ -e /dev/tty ]; then
  "$BIN_DIR/net-auto-switch" init </dev/tty
else
  "$BIN_DIR/net-auto-switch" init --yes
fi

info "Done. Installed $TAG at $INSTALL_DIR"
info "Update later with:  net-auto-switch update"
info "Tab-completion: run 'exec zsh' (or open a new shell) to activate it."
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) info "Add $BIN_DIR to your PATH to use the 'net-auto-switch' command." ;;
esac
