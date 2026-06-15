---
description: Cut a release — verify, bump version, push, publish a GitHub release, redeploy this machine, and verify the deploy
argument-hint: "[patch|minor|major|X.Y.Z] [no-deploy]"
allowed-tools: Bash, Read, Edit, Write
---

You are running the **full net-auto-switch release flow**. Follow the phases in order.
Treat every verification as a gate: if a step fails, **STOP and report** — do not push,
tag, or deploy on top of a failure.

Arguments: `$ARGUMENTS`
- First token = the bump: `patch` (default), `minor`, `major`, or an explicit `X.Y.Z`.
- If `no-deploy` appears anywhere, skip Phase 4 (the machine-local redeploy).

## Phase 0 — Preflight (abort on any problem)

1. Confirm the branch is `main` and the working tree is clean **except** for changes you
   are about to make. The feature/fix commits must already be made — this command only
   adds the version-bump commit. If there are uncommitted feature changes, STOP and tell
   the user to commit them first.
2. `git fetch --tags origin` — the `v0.3.x` tags are created server-side by `gh release`
   and may be absent locally; without this the changelog/previous-tag is wrong.
3. Run the verification gate and require all green:
   - `uv run pytest -q`
   - `uv run ruff check .`
   - `uv run ruff format --check net_auto_switch/ tests/`
   - Secret/personal-path scan (from CLAUDE.md):
     `grep -rn "your-clash-api-secret\|/Users/[a-z]\+/\|/home/[a-z]\+/" --include="*.py" net_auto_switch/ tests/` — expect no matches (`config.example.toml` is the only allowed placeholder, and it's not scanned here).

## Phase 1 — Version bump

1. Read the current `version` from `pyproject.toml`.
2. Compute the new version from the bump argument (default `patch`). The repo bumps
   **patch** even for features — match that unless told otherwise.
3. Edit `pyproject.toml` to the new version, then `uv sync` (refreshes `uv.lock`).
4. Commit just the bump:
   ```
   git add pyproject.toml uv.lock
   git commit -m "chore: bump version to X.Y.Z" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
   ```

## Phase 2 — Push

`git push origin main`.

## Phase 3 — GitHub release

1. Determine the previous tag: `git describe --tags --abbrev=0 HEAD^` (after the fetch).
2. Draft release notes from `git log <prevtag>..HEAD --no-merges` in the repo's
   established format:
   - Title: `vX.Y.Z — <short human summary>`
   - A one-line lead, then `## Fixed` / `## Changed` / `## Added` sections as warranted.
   - The install one-liner:
     `curl -fsSL https://raw.githubusercontent.com/OctopusGarage/net-auto-switch/main/install.sh | bash`
   - `**Full Changelog**: https://github.com/OctopusGarage/net-auto-switch/compare/<prevtag>...vX.Y.Z`
   Reference an ADR if the release introduced one. Show the user the draft, then create it:
   ```
   gh release create vX.Y.Z --target main --title "vX.Y.Z — …" --notes-file - <<'EOF'
   …notes…
   EOF
   ```
3. Verify: `gh release list -L 3` shows `vX.Y.Z` as **Latest**, and
   `git ls-remote --tags origin vX.Y.Z` resolves.
4. The `release.yml` workflow (triggered by the tag push) builds and attaches the
   curated lean asset `net-auto-switch-vX.Y.Z.tar.gz` (+ `.sha256sum`) — ADR-0014.
   Wait for it, then confirm: `gh release view vX.Y.Z --json assets`.
5. Self-consistency check (matters because install/update pull the *latest release's*
   asset — ADR-0014, falling back to the source archive): download
   `https://github.com/OctopusGarage/net-auto-switch/releases/download/vX.Y.Z/net-auto-switch-vX.Y.Z.tar.gz`
   and spot-check a changed file + that it's lean (no `tests/`, `.github/`).

## Phase 4 — Redeploy this machine (skip if `no-deploy`; macOS only)

The daemon runs in place from `~/.net-auto-switch` (override `NET_AUTO_SWITCH_DIR`).
Migrate it to the new release via the tarball mechanism (ADR-0014), preserving
`config.toml` (gitignored → not in the archive) and `.venv`:

1. Resolve latest tag via the redirect, download its **asset** (fall back to the
   source archive), and extract over the install dir, dropping any old `.git`:
   ```
   INSTALL_DIR="$HOME/.net-auto-switch"; REPO="OctopusGarage/net-auto-switch"
   url=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")
   TAG="${url##*/}"; tmp="$(mktemp -d)"
   curl -fsSL "https://github.com/$REPO/releases/download/${TAG}/net-auto-switch-${TAG}.tar.gz" -o "$tmp/r.tar.gz" \
     || curl -fsSL "https://github.com/$REPO/archive/refs/tags/${TAG}.tar.gz" -o "$tmp/r.tar.gz"
   [ -d "$INSTALL_DIR/.git" ] && rm -rf "$INSTALL_DIR/.git"
   tar -xzf "$tmp/r.tar.gz" --strip-components=1 -C "$INSTALL_DIR"; rm -rf "$tmp"
   (cd "$INSTALL_DIR" && uv sync)
   ```
2. Restart the launchd service and capture the new PID:
   ```
   launchctl kickstart -k gui/$(id -u)/com.octopusgarage.net-auto-switch
   ```

## Phase 5 — Verify the deploy (skip if `no-deploy`)

1. `~/.local/bin/net-auto-switch update --no-restart` → expect `✓ Already up to date (vX.Y.Z)`.
2. `pgrep -fl net_auto_switch.cli` shows a fresh PID running from `~/.net-auto-switch`.
3. Tail `~/Library/Logs/net_auto_switch.log` for a healthy cycle (e.g.
   `Rule mode: managing 'Proxy'` then `No switch needed` / `Switched`).

## Report

Summarize: new version, commit SHAs, release URL, redeploy PID, and the verification
results. If you stopped early, say exactly which gate failed and what's needed.
