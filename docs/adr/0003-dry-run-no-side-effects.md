# ADR-0003: `--dry-run` Must Be Side-Effect-Free

**Date:** 2026-05-29
**Status:** Accepted

## Context

`--dry-run` is meant to show what the daemon *would* do without changing anything.
The final node / WiFi switches were correctly gated, but Tokyo IP-enrichment
(`enrich_tokyo_via_ip`) calls `get_node_region`, which issues a real `switch_proxy`
PUT to probe each node's IP — a hidden side effect that changed the active node
even under `--dry-run`.

## Decision

Treat "no real switch of any kind" as the dry-run contract. `run_cycle` skips
`enrich_tokyo_via_ip` entirely when `dry_run=True`; Tokyo grouping then falls back
to name-based classification only. The node switch and the profile fallback are
likewise gated.

## Consequences

- `--dry-run` is safe to run against a live Clash instance with no observable change.
- Dry-run Tokyo classification is name-only (no IP refinement) — acceptable, since
  dry-run is for inspection, not precision.
- Regression tests assert `enrich_tokyo_via_ip` / `switch_proxy` / `get_node_region`
  are not called during dry-run.
