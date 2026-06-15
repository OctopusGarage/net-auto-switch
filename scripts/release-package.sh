#!/bin/bash
# Build a lean release tarball + SHA-256 checksum into dist/.
#
# GitHub's auto-generated "Source code" archive ships the whole repo (tests, CI
# configs, dev tooling). This curated allowlist keeps the download small and means
# new dev files never leak into a release. The installer (install.sh / the `update`
# command) prefers this asset and falls back to the source archive.
#
# Usage: scripts/release-package.sh <version>   # e.g. v0.3.5 or 0.3.5
set -euo pipefail

VERSION="${1:-}"
[ -n "$VERSION" ] || {
  echo "Usage: scripts/release-package.sh <version>" >&2
  exit 1
}
case "$VERSION" in v*) ;; *) VERSION="v$VERSION" ;; esac

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
PKG="net-auto-switch-$VERSION"
TMP="$(mktemp -d)"
STAGE="$TMP/$PKG"
TARBALL="$DIST_DIR/$PKG.tar.gz"
SUMFILE="$DIST_DIR/$PKG.tar.gz.sha256sum"
trap 'rm -rf "$TMP"' EXIT

# Runtime allowlist — anything not listed here is intentionally excluded.
INCLUDE=(
  net_auto_switch
  scripts
  completions
  pyproject.toml
  uv.lock
  .python-version
  config.example.toml
  install.sh
  README.md
  LICENSE
)

for item in "${INCLUDE[@]}"; do
  [ -e "$ROOT_DIR/$item" ] || {
    echo "Missing required path for release package: $item" >&2
    exit 1
  }
done

mkdir -p "$STAGE" "$DIST_DIR"
for item in "${INCLUDE[@]}"; do
  cp -R "$ROOT_DIR/$item" "$STAGE/"
done

# Drop dev-only artifacts that live under the included directories.
rm -rf "$STAGE/net_auto_switch/__pycache__"
find "$STAGE" -name '*.pyc' -delete
rm -f "$STAGE/scripts/pre-commit" "$STAGE/scripts/install-hooks.sh" \
  "$STAGE/scripts/release-package.sh"

rm -f "$TARBALL" "$SUMFILE"
tar -czf "$TARBALL" -C "$TMP" "$PKG"

# Portable SHA-256 (Linux sha256sum / macOS shasum).
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$DIST_DIR" && sha256sum "$(basename "$TARBALL")" >"$SUMFILE")
else
  (cd "$DIST_DIR" && shasum -a 256 "$(basename "$TARBALL")" >"$SUMFILE")
fi

echo "Built $TARBALL"
cat "$SUMFILE"
