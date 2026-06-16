# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Each release also has full notes on the [Releases page](https://github.com/OctopusGarage/net-auto-switch/releases).

## [0.2.3] - 2026-06-16

### Added
- Agent skill ([`skills/net-auto-switch`](skills/net-auto-switch/SKILL.md)) — a Claude Code / cross-agent skill teaching an AI agent to operate and diagnose the tool (current node, operator behind a host, live connections, service status, update). `install.sh` offers to install it; or run `npx skills add OctopusGarage/net-auto-switch -y -g`.

### Fixed
- `connections -w` (watch) is now responsive: `q` or Ctrl-C quits immediately (previously Ctrl-C could hang while `--whois` worker threads were mid-lookup), the redraw is flicker-free (in-place repaint instead of a full-screen clear), and the cursor is hidden during watch.
- `connections --whois` caches only successful lookups, so a transient DoH/whois failure retries on the next tick instead of being pinned as a permanent blank for the session.
- `connections -w` exits cleanly on stdin EOF instead of busy-looping.
- The whois profile-scan test now passes on the windows-latest CI matrix (Windows tmp paths were breaking TOML parsing).

### Changed
- Internal: the concurrent whois fan-out is shared between the profile scan and connections enrichment.

## [0.2.2] - 2026-06-15

### Added
- `net-auto-switch connections` — list what the machine is contacting right now and through which outbound node, read from Clash's `/connections` API (`host → node → rule`). Rows are folded by `host + node` with a connection count (`--raw` lists each); `--whois` labels each target's IP / operator / country, resolving the domain itself when Clash exposes no IP (proxied connections); `-w/--watch` refreshes live. Only sees traffic that goes through Clash (proxied / TUN), not direct/bypassed traffic.
- zsh tab-completion for every subcommand and flag, bundled in the release tarball and registered idempotently by `install.sh` — re-installing never duplicates the `~/.zshrc` block, and `update` refreshes the completion in place.

### Changed
- The `whois` Clash-profile scan now runs lookups concurrently (≤8) and prints per-server `[n/N]` progress to stderr, so a large profile no longer looks frozen for minutes. The stdout table is unchanged.

## [0.2.1] - 2026-06-15

### Added
- `net-auto-switch whois` with no targets now reads the current Clash Verge profile and resolves each proxy `server`, de-duplicating repeated hosts before lookup. Output groups rows under the current profile uid/name and includes node name, server, resolved IP, operator, and country.

### Changed
- Split whois lookups into reusable result objects while preserving the existing explicit-target output path.

## [0.2.0] - 2026-06-15

### Added
- Cross-platform core — the Clash selection/switching loop only talks to the Clash Verge API over HTTP, so it runs on Linux/Windows too. macOS-only features degrade gracefully: WiFi switching and profile fallback are skipped off macOS; notifications use `notify-send` on Linux, no-op on Windows. ([ADR-0015](docs/adr/0015-cross-platform-core.md))
- `service install / uninstall / status` — one command, platform-native: launchd (macOS), systemd `--user` (Linux, `Restart=always` + linger), Task Scheduler running `--once` every `main_interval` minutes (Windows). ([ADR-0016](docs/adr/0016-cross-platform-service.md))
- CI matrix across ubuntu + macOS + windows.

### Notes
- macOS behavior is unchanged. On Linux/Windows: copy `config.example.toml` → `config.toml`, fill in your Clash API settings, then `net-auto-switch service install`.

## [0.1.0] - 2026-06-15

Initial release — a layered network self-healing daemon for macOS that auto-switches WiFi and Clash Verge proxy nodes/profiles to keep you online with a good proxy.

### Added
- Layered auto-switch — WiFi (physical) then Clash (proxy) every cycle; config-driven region groups, latency-based selection with priority fallback, profile fallback when all nodes are dead.
- Guided `init` wizard — auto-detects Clash Verge, infers regions, gates on a health check.
- macOS switch notifications (with exit operator) and a standalone `whois` lookup (DoH by default).
- `curl | bash` installer pulling a curated lean release asset; self-updating `update`; launchd service.

[0.2.3]: https://github.com/OctopusGarage/net-auto-switch/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/OctopusGarage/net-auto-switch/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/OctopusGarage/net-auto-switch/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/OctopusGarage/net-auto-switch/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/OctopusGarage/net-auto-switch/releases/tag/v0.1.0
