# ADR-0005: Guided Setup Wizard (`init`)

**Date:** 2026-06-08
**Status:** Accepted

## Context

The only hard part of onboarding was hand-editing `config.toml`: a new user had
to dig the Clash API secret, controller port, proxy port, and `profiles.yaml`
path out of Clash Verge, plus tune region patterns to their own subscription.
Placeholder values meant the daemon wouldn't run until edited, with no feedback.

Clash Verge writes its merged runtime config to
`~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml`,
which contains `external-controller`, `secret`, and `mixed-port` — i.e. every
machine-specific value can be auto-detected.

## Decision

Add a `net-auto-switch init` subcommand that auto-detects those values, probes
the Clash API to confirm, previews the detected node groups, writes a complete
commented `config.toml` (backing up any existing one), validates it, and offers
to install the launchd service. `--yes` runs it non-interactively.

Detection/render logic lives in `setup.py` as pure functions
(`parse_verge_runtime`, `render_config_toml`) so it stays unit-testable; the
wizard reuses `install-launchd.sh` rather than duplicating service setup.

## Consequences

- New users get from clone to running with one command; manual `cp
  config.example.toml config.toml` remains supported for non-Verge setups.
- The detected secret is written into the gitignored `config.toml` (see
  [ADR-0002](0002-config-externalization-toml.md)); it never enters source.
- A Clash-Verge-specific path is now baked into the wizard; non-default install
  locations fall back to the manual flow.
