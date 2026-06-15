# net-auto-switch

[![CI](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml/badge.svg)](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](.python-version)

**English** · [简体中文](README.zh-CN.md)

A **layered network self-healing daemon** for macOS: the lower layer switches WiFi on demand, the upper layer auto-switches Clash Verge nodes / subscriptions. When the network degrades, it restores connectivity and proxy quality without manual intervention.

## Features

- **Layered orchestration** — each round checks WiFi (physical layer) first, then Clash (proxy layer): "first make sure you're online, then make sure the proxy is good."
- **WiFi layer is optional + low-frequency** — toggle it on; an independent check interval plus a switch cooldown prevent flapping.
- **Smart Clash node selection** — grouped by configurable regions (default SG → Tokyo → JP_Other), latency-tested with priority fallback.
- **Profile fallback** — when every node is unreachable, switch the subscription via AppleScript.
- **Fully externalized config** — thresholds / intervals / ports / secret / region regexes all live in `config.toml`; the secret is never committed.
- **`--dry-run`** — rehearsal mode with zero side effects (no real switching).
- **Fault isolation** — a transient error in any one layer never takes down the daemon.
- **Launch at boot** — a launchd service with `RunAtLoad` + `KeepAlive` (auto-restart on crash).

## Feature Overview

| Area | What it does |
|------|--------------|
| **Layered orchestration** | Each cycle runs the WiFi layer first, then the Clash layer — get online, then optimize the proxy. Layers are isolated: a failure in one never affects the other or kills the daemon. |
| **WiFi layer** (optional, low-frequency) | Detects the current network and ping-tests latency / loss; flags a "bad" network past your thresholds; builds candidates from *preferred ∩ currently-visible* networks; switches only if a candidate is faster by at least `min_improvement_ms`. Guarded by a separate check interval **and** a post-switch cooldown. |
| **Clash node selection** | Groups nodes by region (SG / Tokyo / JP_Other, regex-configurable); keeps the current node while it's stable (`delay_limit`); otherwise speed-tests and picks the best in-group, falling back across regions by `group_priority`. JP nodes that don't name a city are checked by IP geolocation to spot Tokyo. |
| **Profile fallback** | When every node is unreachable, switches the subscription profile via AppleScript UI automation. |
| **Rate limiting** | Node switches ≤ `max_switch_per_min`; profile switches ≤ `max_profile_switch_per_30min`. |
| **Desktop notifications** | On every real switch (Clash node / profile / WiFi) a macOS banner shows what changed — for node switches it includes the exit operator (AWS / 腾讯云 / …). Toggle with top-level `notify`; never fires under `--dry-run`. |
| **Run modes** | Long-running daemon, single cycle (`--once`), and zero-side-effect rehearsal (`--dry-run`); custom config via `--config`. |
| **Install & ops** | One-line `curl` installer, guided `init` wizard (auto-detects Clash Verge), one-command `update`, and a launchd service (boot start + crash restart). Logs rotate daily and self-clean after 14 days. |
| **Config & safety** | Everything tunable lives in `config.toml` (validated on load); the secret is never committed — only `config.example.toml` is tracked. |

## Architecture

```
cli.py  (argparse entry: --once / --dry-run / --config + logging)
   │
   └── orchestrator.py  (main loop: WiFi first → Clash; rate/cooldown; fault isolation)
         ├── wifi.py    (WiFi layer: probe/scan/switch via networksetup/system_profiler/ping)
         ├── clash.py   (ClashController: grouping/selection/node switch/profile fallback)
         └── config.py  (TOML load → dataclass + validation)
```

See [`CONTEXT.md`](CONTEXT.md) (domain glossary & invariants) and [`docs/adr/`](docs/adr/) (architecture decisions).

## Quick Start

### One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/OctopusGarage/net-auto-switch/main/install.sh | bash
```

Installs [uv](https://docs.astral.sh/uv/) if needed, downloads the **latest release**
into `~/.net-auto-switch`, syncs deps, adds a global `net-auto-switch` command, and
runs the guided `init` wizard. Re-run it any time — it updates an existing install.
Pin a version with `NET_AUTO_SWITCH_VERSION=v0.3.4`.

### Manual install

```bash
git clone https://github.com/OctopusGarage/net-auto-switch.git
cd net-auto-switch
uv sync                  # create .venv (Python pinned by .python-version) and install deps
uv run net-auto-switch init   # guided setup — see below
```

Prefer a download? Every [release](https://github.com/OctopusGarage/net-auto-switch/releases)
ships an auto-generated source tarball / zip.

### Guided setup (`init`)

`init` reads your Clash Verge config to **auto-detect** the API endpoint, secret,
proxy port, and `profiles.yaml` path, verifies the connection, **runs a health
check** (aborting with guidance if no nodes are reachable), **checks each
subscription's auto-update / expiry / traffic and guides you to fix stale ones**,
**scans your subscription's actual nodes to detect which regions you have (US, JP,
HK, …) and lets you choose which to prioritize**, writes `config.toml` (backing up
any existing one), and offers to install the launchd service:

```bash
uv run net-auto-switch init          # interactive
uv run net-auto-switch init --yes    # non-interactive (accept all defaults)
```

At every step `init` checks the environment and tells you exactly what to fix —
if you're not on macOS, Clash Verge isn't installed / hasn't run / isn't
reachable, the secret is wrong, or there are no working nodes.

Prefer to configure by hand (or not using Clash Verge)? Copy the template
instead: `cp config.example.toml config.toml` and edit it.

```bash
# Verify without switching anything
uv run net-auto-switch --once --dry-run
```

### Updating

```bash
net-auto-switch update    # download the latest release, re-sync deps, reload the service
```

Updates pull the latest published release (skipping the download if you're already
current); `--version vX.Y.Z` installs a specific release and `--force` reinstalls.
`config.toml` is never touched. (For a manual clone: `git pull && uv sync`, then
re-run `./scripts/install-launchd.sh`.)

## Usage

```bash
uv run net-auto-switch init                 # guided setup (see Quick Start)
uv run net-auto-switch update               # update to the latest version
uv run net-auto-switch --once --dry-run    # single round, rehearsal
uv run net-auto-switch --once              # single round
uv run net-auto-switch                      # long-running
uv run net-auto-switch --config /path/to/config.toml
uv run net-auto-switch whois <domain|ip>…   # which operator / cloud owns a host
```

`whois` is a standalone lookup (independent of the daemon): it resolves a domain
to its IP(s), runs `whois`, and labels the owning operator / cloud provider
(腾讯云, AWS, Cloudflare…). It resolves via **Cloudflare DoH by default** so it sees
the real address even under TUN-mode DNS hijacking; pass `--no-doh` for plain system
DNS, or `-a` to query the domain's authoritative NS. `whois -h` shows all options.

`uv run net-auto-switch` is equivalent to `uv run python -m net_auto_switch.cli`.

### Process management scripts

```bash
./scripts/start.sh    # start in background (writes .net-auto-switch.pid)
./scripts/status.sh   # is it running?
./scripts/stop.sh     # stop it
```

## Configuration

All settings live in `config.toml` (template: `config.example.toml`).

| Key | Default | Description |
|-----|---------|-------------|
| `main_interval` | `600` | Main loop interval (seconds) |
| `wifi.enabled` | `true` | Enable the WiFi layer |
| `wifi.check_interval` | `3600` | WiFi check interval (seconds) |
| `wifi.switch_cooldown` | `7200` | Cooldown after a WiFi switch (seconds) |
| `wifi.bad_latency_ms` | `200` | Latency threshold for "bad network" |
| `wifi.bad_loss_pct` | `5` | Packet-loss threshold for "bad network" (%) |
| `wifi.min_improvement_ms` | `100` | Only switch if improvement reaches this |
| `wifi.interface` | `en0` | WiFi interface |
| `clash.api` | `http://127.0.0.1:9097` | Clash external-control API |
| `clash.secret` | *(required)* | Clash API secret |
| `clash.proxy_port` | `7890` | Clash HTTP proxy port (used for IP geolocation) |
| `clash.delay_limit` | `300` | Stability threshold for the current node (ms) |
| `clash.max_switch_per_min` | `3` | Max node switches per minute |
| `clash.max_profile_switch_per_30min` | `1` | Max profile switches per 30 minutes |
| `clash.profiles_yaml` | *(Clash Verge path)* | Location of `profiles.yaml` |
| `clash.group_priority` | `["SG","Tokyo","JP_Other"]` | Region fallback priority (names must be defined in `regions`) |
| `clash.trial` | `试用` | Nodes whose name matches this regex are ignored |
| `clash.regions` | SG / Tokyo / JP_Other | Region name → regex, matched in order (first match wins). Fully configurable |
| `clash.ip_enrich` | Tokyo ← JP_Other | Optional: reclassify nodes into a region by IP geolocation; remove to disable |

**Custom regions** — `regions` is fully configurable, so you can prefer any region.
For a US-first setup:

```toml
group_priority = ["US", "JP", "SG"]

[clash.regions]
US = "(US|United States|美国|🇺🇸)"
JP = "(JP|Japan|日本|🇯🇵)"
SG = "(SG|Singapore|新加坡|🇸🇬)"
```

Nodes are classified by the **first** matching region (define more specific ones
first); anything matching none is left untouched.

## Production Deployment (macOS launchd)

Run as a launchd service: launch at boot + auto-restart on crash.

```bash
./scripts/install-launchd.sh     # install deps + generate plist + register & load
./scripts/uninstall-launchd.sh   # unload

# Inspect manually
launchctl list com.octopusgarage.net-auto-switch
tail -f logs/launchd.err.log
```

**What it gives you:**
- `RunAtLoad` — starts at boot.
- `KeepAlive` + `ThrottleInterval=10` — auto-restart on crash, with a 10s minimum interval (crash-loop guard).
- launchd stdout/stderr → `logs/launchd.out.log` / `logs/launchd.err.log`.

## Resilience

| Mechanism | Behavior |
|-----------|----------|
| Layer isolation | WiFi / Clash each wrapped in try/except; one layer failing affects neither the other nor the process |
| Clash API error | `RequestException` caught, logged, then on to the next round |
| All nodes down | Auto-switch the subscription profile as a fallback (rate-limited to 30 min) |
| Switch rate limit | Nodes ≤ 3/min, profiles ≤ 1/30 min |
| Process self-heal | launchd `KeepAlive` auto-restarts on crash |

## Logs

- **Program log (authoritative):** `~/Library/Logs/net_auto_switch.log` — **rotated at midnight daily, cleaned up after 14 days** (`TimedRotatingFileHandler`); never grows unbounded.
- When run via launchd: stdout is discarded (`/dev/null`, to avoid duplicating the rotated log); `logs/launchd.err.log` only captures crashes that happen before the logging system initializes (normally empty).
- When run via `start.sh`: output is appended to `logs/net-auto-switch.out.log` (for development).

Retention is controlled by `LOG_BACKUP_DAYS` in `cli.py` (default 14).

## Project Layout

```
net-auto-switch/
├── net_auto_switch/     # package: config / setup / wifi / clash / orchestrator / whois / cli
├── tests/               # pytest unit tests
├── scripts/             # ops scripts + launchd plist + wrapper
├── docs/
│   └── adr/             # architecture decision records
├── install.sh           # one-line curl installer (bootstrap)
├── config.example.toml  # config template (config.toml is gitignored)
├── CONTEXT.md           # domain glossary & invariants
├── pyproject.toml       # dependencies + tool config (pytest / ruff)
├── uv.lock              # uv-locked dependency versions (committed)
└── .python-version      # pinned Python version (read by uv)
```

## Testing

```bash
uv run pytest          # full unit-test suite
uv run ruff check .    # static checks
uv run ruff format .   # format
```

## Requirements

- macOS, with [uv](https://docs.astral.sh/uv/) (auto-manages Python 3.12, see `.python-version`).
- Clash Verge running with external control enabled (API port & secret matching the config).
- WiFi switching needs the relevant system permissions; profile fallback depends on authorizing **System Settings → Privacy & Security → Accessibility**.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © Kingson Wu
