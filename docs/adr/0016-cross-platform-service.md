# ADR-0016: Cross-Platform Service Install

**Date:** 2026-06-15
**Status:** Accepted (builds on ADR-0015)

## Context

ADR-0015 made the Clash core run on Linux/Windows, but a switcher only matters if it
keeps running. Each OS has a different native way to run a per-user background job,
and none should require a third-party supervisor.

## Decision

One command — `net-auto-switch service install|uninstall|status` — dispatches to the
platform-native mechanism (`net_auto_switch/service.py`):

- **macOS** → launchd LaunchAgent, long-running daemon (reuses the existing
  `scripts/install-launchd.sh`, `RunAtLoad` + `KeepAlive`).
- **Linux** → systemd `--user` service: a generated unit with `Restart=always`,
  enabled with `systemctl --user enable --now`, plus `loginctl enable-linger` so it
  survives logout.
- **Windows** → a Task Scheduler task (`schtasks /Create … /SC MINUTE /MO N`) that
  runs `net-auto-switch --once` every `main_interval` minutes.

The unit/command text is produced by pure `render_*` functions (unit-tested); the
entry points only shell out to `launchctl` / `systemctl` / `schtasks`.

## Consequences

- macOS and Linux run a continuous daemon; Windows runs a scheduled one-shot. The
  `--once` model fits Task Scheduler (which has no daemon supervision) and is fine
  since the only stateful layer (WiFi) is macOS-only anyway.
- The render functions are tested on all three CI OSes, but **actual registration**
  (a live systemd/Task Scheduler service driving a real Clash instance) is not
  exercised in CI — it needs a real Linux/Windows host to confirm end-to-end.
- A future improvement could unify on the `--once`-on-a-timer model everywhere
  (launchd `StartInterval`, systemd timer); deferred to avoid changing the working
  macOS daemon.
