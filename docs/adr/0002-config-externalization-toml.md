# ADR-0002: Externalize Configuration to TOML

**Date:** 2026-05-29
**Status:** Accepted

## Context

The original scripts hardcoded the Clash API secret (`your-clash-api-secret`), ports, latency
thresholds, region regexes, and intervals. This leaked a secret into source and
made every tweak a code edit.

## Decision

Move all tunables into `config.toml`, loaded by `config.py` into typed dataclasses
with safe defaults. The dataclass defaults are the single source of truth;
`load_config` fills absent keys from them. The real `config.toml` is gitignored;
`config.example.toml` is the tracked template and the only place a placeholder
secret appears.

## Consequences

- No secret in tracked source; `secret` defaults to `""`.
- Thresholds / intervals / regexes are editable without touching code.
- Config is validated at load (positive intervals, valid port range) and fails
  fast with a clear message that points at `config.example.toml`.
- Tests construct configs directly from the dataclasses — no files needed.
