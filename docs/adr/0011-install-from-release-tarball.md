# ADR-0011: Install/update from the latest release tarball, not `git clone main`

**Date:** 2026-06-09
**Status:** Accepted (amends [ADR-0006](0006-distribution-curl-installer.md))

## Context

[ADR-0006](0006-distribution-curl-installer.md) shipped `install.sh` as a
`git clone` of the repo and `net-auto-switch update` as `git pull --ff-only` on
`main`. Two problems followed from tracking `main`:

- **Installs got unreleased code.** Anyone installing between releases got the
  current `main` HEAD — possibly mid-development commits — not a published version.
  The GitHub Releases (with their tags and notes) were effectively decorative; the
  real delivery path ignored them.
- **The release tarball already exists and is already filtered.** `.gitattributes`
  marks `tests/`, `.github/`, `docs/`, `CLAUDE.md`, etc. as `export-ignore`, so the
  per-release "Source code" tarball GitHub generates via `git archive` already
  contains only runtime files. Nothing consumed it.

## Decision

Install and update from the **latest published release's source tarball**, pinned
to its tag, instead of cloning `main`:

- Resolve the target tag by following the `…/releases/latest` redirect (no `jq`,
  no API token); `NET_AUTO_SWITCH_VERSION=vX.Y.Z` pins a specific release.
- Download `…/archive/refs/tags/<tag>.tar.gz` (the export-ignore-filtered archive)
  and extract it over `~/.net-auto-switch` with `--strip-components=1`. `config.toml`
  is gitignored, so it's absent from the archive and preserved untouched; `.venv` is
  likewise left in place and refreshed by `uv sync`.
- `net-auto-switch update` resolves the latest tag, compares it to the installed
  `pyproject.toml` version, and downloads only when newer (`--force` / `--version`
  override). It no longer shells out to `git`.
- `install.sh` removes a prior install's `.git` directory, migrating existing
  git-clone installs to the tarball model in place.

The in-place uv-run model from ADR-0006 is unchanged: the daemon still runs from the
extracted source via `uv run --project`, with the launchd plist at a stable path.
Only the *delivery mechanism* changes. No custom release asset or CI build step is
needed — GitHub's existing filtered source tarball is the artifact.

## Consequences

- Installs and updates now track **released versions**, not arbitrary `main`; the
  GitHub Releases become the real distribution channel they looked like.
- `git` is no longer a runtime/install dependency (only `curl` + `tar`, both present
  on macOS); the manual `git clone` path stays documented for development.
- Updates are idempotent and version-aware: "already up to date" short-circuits
  before any download.
- **Coupling to the release cadence:** a fix isn't available to installers until a
  release is cut and tagged — which is the intended behavior, and matches how the
  releases were already being published.
