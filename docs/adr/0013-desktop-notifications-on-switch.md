# ADR-0013: Desktop Notifications on Switch

**Date:** 2026-06-15
**Status:** Accepted

## Context

The daemon's switches were only visible in the rotating log file. Users wanted a
real-time, glanceable signal — a macOS banner — telling them when and where the
network changed (which node, which exit operator, which WiFi).

## Decision

A new `net_auto_switch/notify.py` sends macOS notifications via
`osascript -e 'display notification …'` — the same dependency-free AppleScript
mechanism already used for profile switching. It is **best-effort**: any failure is
logged and swallowed so a missing banner never disturbs switching.

Notifications fire on all three real switch events:

- **Clash node switch** — title shows the node, subtitle the exit operator (reuses
  `get_exit_operator`, see ADR-0012).
- **Profile fallback** — when every node is dead and the subscription is switched.
- **WiFi switch** — when the daemon moves to a better network.

A top-level `notify` config flag (default **on**) gates the feature. The flag is
threaded to `ClashController(notify=…)` so unit tests, which construct controllers
directly, default to `notify=False` and never shell out to `osascript`.

## Consequences

- Notifications are a user-facing side effect, so they obey the ADR-0003 contract:
  **never fire under `--dry-run`** (the Clash branches are already non-dry-run; the
  WiFi path is explicitly gated on `not self.dry_run`).
- macOS-only, consistent with the project's platform scope.
- Default-on changes prior behavior (silent daemon); set `notify = false` to opt out.
