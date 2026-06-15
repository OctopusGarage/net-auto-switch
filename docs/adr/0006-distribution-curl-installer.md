# ADR-0006: Distribution via curl installer + `update`, not binaries

**Date:** 2026-06-08
**Status:** Accepted (delivery mechanism amended by [ADR-0011](0011-install-from-release-tarball.md) — install/update now pull the latest release tarball instead of `git clone`/`git pull` on `main`; the in-place uv-run model here is unchanged)

## Context

The daemon runs **in place** from a checkout: the launchd plist hard-codes the
project path and invokes `.venv/bin/python` and `config.toml` inside it. Service
setup lives in `scripts/install-launchd.sh`, which is not package data, so the
daemon can't be relocated into `site-packages` without rework.

We wanted an elegant "one command to install and run" plus an easy upgrade path,
and weighed source tarballs, a `curl | bash` installer, a single binary, and a
Homebrew tap.

## Decision

Ship a root `install.sh` (the `curl | bash` target) that installs uv if missing,
clones to a stable `~/.net-auto-switch` (override via `NET_AUTO_SWITCH_DIR`),
syncs deps, drops a global `net-auto-switch` launcher in `~/.local/bin`
(`uv run --project …`), and runs the `init` wizard — reading prompts from
`/dev/tty` so it stays interactive under a pipe. Add a `net-auto-switch update`
subcommand (git pull → re-sync → reload service via `install-launchd.sh`).

This keeps the proven in-place model; no architectural change. Source tarballs
are already provided automatically by GitHub Releases.

## Consequences

- One-line install + one-command update, with the daemon at a stable path that
  survives reboots (see [ADR-0005](0005-guided-setup-wizard.md)).
- **No single binary:** macOS notarization plus re-granting AppleScript/TCC
  permissions on every rebuild outweigh the benefit, and a binary still needs
  `config.toml` and Clash Verge.
- **Homebrew deferred:** a tap is idiomatic but first requires making service
  setup repo-independent (generate the plist in Python, ship scripts as package
  data) — a larger change left for a future ADR.
