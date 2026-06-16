---
name: net-auto-switch
version: 1.0.0
description: "Operate and diagnose net-auto-switch — the macOS daemon that auto-switches the Clash Verge proxy node (and WiFi) by measured network quality. Use when the user asks what proxy node they're on, why the proxy is slow, which operator/cloud is behind a node or domain, what their machine is connecting to right now, or to check / start / stop / update the background service. 诊断代理:当前走哪个节点、某节点或域名属于哪个运营商/云、本机此刻在访问哪些域名、后台服务是否在跑。Not for editing Clash subscriptions or the Clash config itself."
metadata:
  requires:
    bins: ["net-auto-switch"]
  cliHelp: "net-auto-switch --help"
---

# net-auto-switch

net-auto-switch is a long-running macOS daemon that, each cycle, picks a good
Clash Verge proxy **node** (and optionally a better **WiFi**) based on measured
latency / loss, talking to the Clash API. This skill is for *operating and
diagnosing* it from the CLI — it does **not** change your Clash subscription.

Everything is a subcommand of `net-auto-switch` (installed at
`~/.local/bin/net-auto-switch`). Run `net-auto-switch --help` or `<subcommand> -h`
for the full flags.

## Pick the command

| Goal | Command |
|---|---|
| What is the machine connecting to right now, via which node | `net-auto-switch connections` |
| …with operator / country per target | `net-auto-switch connections --whois` |
| …live, top-style (press `q` or Ctrl-C to quit) | `net-auto-switch connections -w` |
| …one row per connection instead of folded counts | `net-auto-switch connections --raw` |
| Which operator / cloud owns a domain or IP | `net-auto-switch whois <domain-or-ip> …` |
| Operator behind every node in the current Clash profile | `net-auto-switch whois` (no args) |
| Is the background service running / install / remove | `net-auto-switch service status` / `install` / `uninstall` |
| Update to the latest release | `net-auto-switch update` |
| Run a single cycle (rehearsal, then real) | `net-auto-switch --once --dry-run`, then `--once` |
| First-time guided setup (macOS) | `net-auto-switch init` |

## Typical scenarios

"My proxy is slow — what node am I on and what's going through it?"

```bash
net-auto-switch connections --whois     # host → node → operator/country → rule
```

"Which provider is behind each node in my current profile?"

```bash
net-auto-switch whois                    # scans the current Clash profile's node servers
```

"Is it actually running?" — always match the module, never bare `python`:

```bash
pgrep -fl net_auto_switch.cli
net-auto-switch service status
tail -f ~/Library/Logs/net_auto_switch.log   # a cycle: delay tests → "No switch needed" / "Switched"
```

## Notes / gotchas

- **macOS-focused.** The node-switching core is cross-platform, but guided `init`,
  WiFi switching, desktop notifications and the launchd service are macOS-only.
- **`connections` only sees traffic that goes through Clash** (proxied / TUN), not
  direct/bypassed traffic, and it's a live snapshot — closed connections drop off.
  For proxied connections Clash exposes no destination IP, so `--whois` resolves
  the host domain itself to label it.
- **`whois` uses Cloudflare DoH by default** to see the real IP under TUN-mode DNS
  hijacking; `--no-doh` for system DNS, `-a` for the authoritative NS. Its
  `country` is the registrant's country, not geo-IP, so it can look "wrong".
- **Config** lives at `~/.net-auto-switch/config.toml` (gitignored; holds the Clash
  API secret). Never print, copy, or commit it.
- **Updating** pulls the latest release tarball in place and reloads the service;
  it preserves `config.toml` and the venv.

## Out of scope

- Editing Clash Verge subscriptions / profiles, or the Clash config itself.
- Non-macOS service setup beyond `net-auto-switch service install` (WiFi / notify /
  `init` are macOS-only).
