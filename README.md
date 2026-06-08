# net-auto-switch

[![CI](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml/badge.svg)](https://github.com/OctopusGarage/net-auto-switch/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](.python-version)

**English** · [简体中文](README.zh-CN.md)

A **layered network self-healing daemon** for macOS: the lower layer switches WiFi on demand, the upper layer auto-switches Clash Verge nodes / subscriptions. When the network degrades, it restores connectivity and proxy quality without manual intervention.

## Features

- **Layered orchestration** — each round checks WiFi (physical layer) first, then Clash (proxy layer): "first make sure you're online, then make sure the proxy is good."
- **WiFi layer is optional + low-frequency** — toggle it on; an independent check interval plus a switch cooldown prevent flapping.
- **Smart Clash node selection** — grouped by region (SG → Tokyo → JP_Other), latency-tested with priority fallback.
- **Profile fallback** — when every node is unreachable, switch the subscription via AppleScript.
- **Fully externalized config** — thresholds / intervals / ports / secret / region regexes all live in `config.toml`; the secret is never committed.
- **`--dry-run`** — rehearsal mode with zero side effects (no real switching).
- **Fault isolation** — a transient error in any one layer never takes down the daemon.
- **Launch at boot** — a launchd service with `RunAtLoad` + `KeepAlive` (auto-restart on crash).

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

This project uses [uv](https://docs.astral.sh/uv/) to manage the virtualenv and dependencies.

```bash
git clone https://github.com/OctopusGarage/net-auto-switch.git
cd net-auto-switch
cp config.example.toml config.toml   # edit secret / port / thresholds
uv sync                               # create .venv (Python pinned by .python-version) and install deps

# Manual rehearsal (no real switching)
uv run net-auto-switch --once --dry-run
```

## Usage

```bash
uv run net-auto-switch --once --dry-run    # single round, rehearsal
uv run net-auto-switch --once              # single round
uv run net-auto-switch                      # long-running
uv run net-auto-switch --config /path/to/config.toml
```

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
| `clash.group_priority` | `["SG","Tokyo","JP_Other"]` | Region fallback priority |
| `clash.patterns.*` | *(regex)* | Recognition regexes for SG / JP / Tokyo / trial |

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
├── net_auto_switch/     # package: config / wifi / clash / orchestrator / cli
├── tests/               # pytest unit tests (46 cases)
├── scripts/             # ops scripts + launchd plist + wrapper
├── docs/
│   └── adr/             # architecture decision records
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
