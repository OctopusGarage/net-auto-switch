# net-auto-switch Domain

## Core job

Keep a macOS machine's network healthy without manual intervention: automatically
pick a good WiFi (physical layer) and a good Clash Verge proxy node (proxy layer).

## Layers

| Layer | Owns | Cadence |
|-------|------|---------|
| **WiFi** (optional) | The associated WiFi network | Low frequency — checked every `wifi.check_interval`; switches respect `wifi.switch_cooldown` |
| **Clash** | The active Clash Verge proxy node + subscription profile | Every main-loop cycle (`main_interval`) |

Order per cycle: **WiFi first** (ensure connectivity), **then Clash** (ensure proxy quality).

## Entities / terms

| Term | Meaning |
|------|---------|
| **Node** | A single Clash proxy (Shadowsocks/Vmess/…). Classified into a Group by its name. |
| **Group** | Region bucket. Config-driven via `clash.regions` (name → regex); fallback order set by `clash.group_priority`. Default: `SG`, `Tokyo`, `JP_Other` (SG → Tokyo → JP_Other). |
| **Profile** | A Clash Verge remote subscription. Switched via AppleScript UI as a last resort. |
| **Delay** | Node latency in ms from Clash's `/delay` probe. `DEAD = 9999` marks unreachable. |
| **Candidate WiFi** | A network that is both *known* (in the preferred list) and *currently visible*. |

## Selection algorithm (Clash) — four invariants

1. **Stability first** — current node delay ≤ `delay_limit` → no switch.
2. **Current group first** — switch within the current region group before leaving it.
3. **Priority downgrade** — only when the current group has nothing usable, fall through the regions in `group_priority` order.
4. **No usable node → no switch** (the profile fallback handles the all-dead case).

## WiFi switching invariants

- Only switches among **candidate** WiFis (known ∩ visible).
- Only switches if improvement ≥ `min_improvement_ms`.
- After a switch, no further WiFi switch until `switch_cooldown` elapses.

## Key invariants

- One main loop; WiFi is gated behind `wifi.enabled` + `check_interval`, Clash runs every cycle.
- Rate limits: ≤ `max_switch_per_min` node switches/min; ≤ `max_profile_switch_per_30min` profile switches/30min.
- `--dry-run` performs **no** real switches and **no** IP-probe side effects (see ADR-0003).
- Each layer's failure is isolated — one layer throwing never stops the other or kills the daemon.
- Secrets live only in `config.toml` (gitignored), never in source.

## What this project does NOT own

- **Clash Verge itself** — must already be running with its external controller enabled.
- **The WiFi / proxy infrastructure** — the daemon only selects among what already exists.
