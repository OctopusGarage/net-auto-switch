# ADR-0014: Curated Release Asset (Lean Tarball)

**Date:** 2026-06-15
**Status:** Accepted (refines ADR-0011)

## Context

ADR-0011 made install/update pull the GitHub auto-generated **source archive**
(`/archive/refs/tags/vX.Y.Z.tar.gz`), trimmed by `.gitattributes export-ignore`.
That works, but `export-ignore` is a **blocklist**: every new developer-only file
must be remembered and added, or it leaks into the download. It did leak — a
security/tooling pass added `.claude/`, `.gitleaks.toml`, `SECURITY.md`, and dev
git-hook scripts, none of which were in the list, so they shipped to every install.

## Decision

Ship a **curated release asset** instead, built from an explicit allowlist:

- `scripts/release-package.sh <tag>` stages only the runtime paths
  (`net_auto_switch/`, `pyproject.toml`, `uv.lock`, `.python-version`,
  `config.example.toml`, the runtime `scripts/`, `install.sh`, `README.md`,
  `LICENSE`), strips `__pycache__` / dev scripts, and produces
  `net-auto-switch-<tag>.tar.gz` + a `.sha256sum`.
- `.github/workflows/release.yml` runs it on every `v*` tag push and attaches the
  asset (+ checksum) to the release.
- `install.sh` and the `update` command download the asset first and **fall back**
  to the source archive for older releases that predate it.
- `.gitattributes export-ignore` is kept and extended as defense-in-depth, so the
  fallback source archive is lean too.

An allowlist fails safe: a new untracked-at-release file is simply not copied, so
it can never bloat a download.

## Consequences

- Downloads contain only what's needed to run (≈90 KB vs the full repo).
- Releases must carry the asset. The local `/release` flow creates the release and
  the workflow attaches the asset on the tag push; the workflow also creates the
  release if a bare tag is pushed, so the asset is never missing.
- Adding a new runtime file means adding it to the `INCLUDE` allowlist (a visible,
  reviewed change) rather than silently inheriting it.
