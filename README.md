# net-auto-switch

A layered macOS network self-healing daemon for WiFi and Clash Verge.

[![Release](https://img.shields.io/github/v/release/OctopusGarage/net-auto-switch)](https://github.com/OctopusGarage/net-auto-switch/releases/latest)
[![CI](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml/badge.svg)](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml)
[![CodeQL](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/codeql.yml/badge.svg)](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/codeql.yml)
[![Gitleaks](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/gitleaks.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**English** | [Simplified Chinese](README.zh-CN.md)

## Why

When the network degrades, the problem may be physical WiFi, a weak proxy node, an expired subscription, or a stale Clash profile. `net-auto-switch` separates those layers and repairs them in order: get online first, then optimize proxy quality.

## Features

- **Layered orchestration** - run WiFi checks before proxy checks.
- **Optional WiFi healing** - scan visible networks, compare latency/loss, and switch only when improvement is meaningful.
- **Smart Clash node selection** - group nodes by region, test delay, and fall back by priority.
- **Profile fallback** - switch Clash Verge subscriptions when every node fails.
- **Dry-run mode** - rehearse a full cycle with zero side effects.
- **Rate limits and cooldowns** - avoid flapping between nodes, profiles, or WiFi networks.
- **Desktop notifications** - show real switches, including exit operator labels when available.
- **Launch at login** - install a `launchd` service with auto-restart and log rotation.

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/OctopusGarage/net-auto-switch/main/install.sh | bash
```

The installer downloads the latest release, syncs dependencies with `uv`, creates a global `net-auto-switch` command, and runs the guided setup wizard.

Manual setup:

```bash
git clone https://github.com/OctopusGarage/net-auto-switch.git
cd net-auto-switch
uv sync
uv run net-auto-switch init
```

## Daily Commands

```bash
net-auto-switch init
net-auto-switch --once --dry-run
net-auto-switch --once
net-auto-switch
net-auto-switch update
net-auto-switch whois github.com
net-auto-switch connections --whois
```

## How It Works

```text
cli.py
  -> orchestrator.py
       -> wifi.py
       -> clash.py
       -> config.py
```

Each cycle:

1. Load and validate `config.toml`.
2. Check the WiFi layer if enabled.
3. Check current Clash group/node health.
4. Keep the current node if it is healthy.
5. Test candidates inside the preferred group.
6. Fall back across configured regions.
7. Fall back to profile switching if all nodes are unreachable.
8. Notify only on real switches.

## Configuration

All tunable values live in `config.toml`; `config.example.toml` is the tracked template.

Key areas:

| Area | What you control |
|---|---|
| Clash API | Controller port, secret, group name, proxy port, profile path. |
| Regions | Regex groups such as SG, Tokyo, JP_Other, HK, or US. |
| Thresholds | Delay limits, packet loss, minimum improvement, required domains. |
| Rate limits | Max node switches per minute and profile switches per 30 minutes. |
| Notifications | macOS banner toggles and switch summaries. |

## Safety Design

- `--dry-run` performs checks without switching WiFi, nodes, or profiles.
- Config secrets are not committed; only examples are tracked.
- A failure in one layer is logged and isolated from the rest of the daemon.
- Cooldowns and rate limits reduce oscillation.
- Logs rotate daily and self-clean after 14 days.

## Service Management

```bash
./scripts/install-launchd.sh
./scripts/service.sh status
./scripts/service.sh logs
./scripts/service.sh restart
./scripts/uninstall-launchd.sh
```

Or use the installed command and guided setup:

```bash
net-auto-switch init
```

## Agent Skill

The repository includes an agent skill for diagnosing network state, current node, host ownership, and daemon health:

```bash
npx skills add OctopusGarage/net-auto-switch -y -g
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

## Architecture Decisions

Design history lives in [docs/adr](docs/adr/), including layered orchestration, dry-run behavior, release packaging, region detection, profile switching, and cross-platform service work.

## Related

- [git-auto-sync](https://github.com/OctopusGarage/git-auto-sync) - local repo automation with safe staging and notifications.
- [OctopusGarage](https://github.com/OctopusGarage) - small tools for AI agents, local automation, and browser-native products.

## License

MIT
