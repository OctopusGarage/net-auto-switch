# ADR-0015: Cross-Platform Core, macOS-Only Extras

**Date:** 2026-06-15
**Status:** Accepted

## Context

The project began macOS-only — `init` hard-exited on non-Darwin. But the daemon's
core value, **Clash node selection/switching**, only talks to the Clash Verge API
over HTTP and is inherently portable; Clash Verge runs on Linux and Windows too.
What's actually macOS-bound is the OS-integration layer: WiFi (`networksetup`),
desktop notifications (`osascript`), profile fallback (AppleScript UI automation),
service management (launchd), and library paths.

## Decision

Make the **core runnable on Linux/Windows** and **degrade the macOS-only features
gracefully** instead of erroring:

- **WiFi layer** runs only on `sys.platform == "darwin"`; elsewhere it's skipped
  (the Clash layer still runs each cycle).
- **Notifications** dispatch by platform: osascript (macOS), `notify-send` (Linux),
  no-op otherwise — always best-effort.
- **Profile fallback** (AppleScript) is skipped on non-macOS with a log line; there's
  no portable equivalent (the Clash API doesn't expose profile switching).
- **Paths** (log file, Clash Verge `profiles.yaml`) are computed per-platform.
- The **`init` wizard** stays macOS-only (Clash Verge auto-detection + launchd) but
  now prints clear manual setup steps for other platforms instead of a bare error.

## Consequences

- A Linux/Windows user configures `config.toml` by hand and runs the daemon (or
  `--once`); the node auto-switch works identically.
- Service management and the wizard remain manual off macOS — deliberately out of
  scope for this minimal cross-platform pass (a full systemd/Task Scheduler story
  can come later).
- Platform branches are unit-tested by pinning `sys.platform`, so CI (Linux) and a
  macOS dev box exercise the same deterministic paths.
