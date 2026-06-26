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
| **Group** | Two-level region bucket: country (`US`) or country/city (`JP/Tokyo`, `JP/_other`). Recognized from a built-in name catalog (countries + cities + flags); `clash.priority` sets country order, `clash.cities` opts a country into city-level grouping. |
| **Profile** | A Clash Verge remote subscription. Switched via AppleScript UI as a last resort. |
| **Delay** | Node latency in ms from Clash's `/delay` probe. `DEAD = 9999` marks unreachable. |
| **Candidate WiFi** | A network that is both *known* (in the preferred list) and *currently visible*. |

## Selection algorithm (Clash) — four invariants

Grouping is fully offline (no IP probe). The engine derives a downgrade chain from the
current node's group: current city → same-country other cities → `country/_other` →
next country by `clash.priority` order.

1. **Stability first** — current node delay ≤ `delay_limit` → no switch.
2. **Current group first** — switch within the current region group (city or country) before leaving it.
3. **Priority downgrade** — only when the current group has nothing usable, follow the downgrade chain: same-country remaining cities, then `_other`, then the next country in `clash.priority`.
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

### Reachability (optional, `[clash.reachability]`)

When `reachability.required` is non-empty, each latency-alive candidate is probed against
those URLs (via the same `/delay` endpoint). Within a region group the engine prefers
nodes that reach **all** required domains, soft-falling-back to lowest-latency when none
pass. Invariant 1 (stability) is extended: the current node is "keep" only if it is fast
**and** reaches all required domains. Region order (invariants 2–3) is unchanged —
reachability only reorders nodes *within* a group, never across groups. Empty/absent =
feature off. The probe is read-only and runs in `--dry-run` (ADR-0003, ADR-0019).

## Blacklist (opt-in, `[clash.blacklist]`)

Hard-exclude proxy nodes based on geography or operator. Two tiers:

- **Tier 1 — offline pre-filter (every cycle):** A node is removed from all candidate groups before the selection algorithm runs if its name-recognized country, or its entry-whois country, is in `blacklist.countries`; or if its entry operator label matches any `blacklist.operators` pattern; or if it appears in the learned exit-blacklist and has not yet expired.
- **Tier 2 — learned exit-blacklist (post-switch only):** After a real switch, the exit's `(country, operator)` is probed (reusing the ADR-0012 probe). If the exit is in `blacklist.countries` or matches `blacklist.operators`, the node is recorded in a persisted `blacklist.json` (same directory as `config.toml`) with a timestamp. Entries expire after `relearn_days` days so a node is re-verified later. Tier 2 is skipped in dry-run (ADR-0003).

Blacklisting only **removes candidates**; it never changes the four selection invariants. An all-blacklisted group is simply empty and the normal downgrade chain applies. An all-blacklisted node set behaves exactly like today's "no usable node" case.

## What this project does NOT own

- **Clash Verge itself** — must already be running with its external controller enabled.
- **The WiFi / proxy infrastructure** — the daemon only selects among what already exists.
