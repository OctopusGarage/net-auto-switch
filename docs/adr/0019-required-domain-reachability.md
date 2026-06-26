# 19. Required-domain reachability as a selection dimension

Date: 2026-06-26

## Status

Accepted

## Context

Node selection was purely latency-driven: `test_delay()` probes one fixed URL
(`gstatic.com/generate_204`) and the engine picks the lowest-latency reachable node in
the current region group. Passing that generic probe does not mean a node reaches the
sites the user depends on — a node can reach YouTube yet be blocked from Telegram.

## Decision

Add an opt-in `[clash.reachability]` block listing domains that must be reachable. Each
latency-alive candidate is probed against those URLs via the existing
`/proxies/{node}/delay` endpoint, yielding a per-node boolean. Selection gains a
within-group preference for reachable nodes (soft priority: fall back to lowest-latency
when none pass), and the stability rule treats a fast-but-unreachable current node as
switchable. Region-first ordering is unchanged — reachability is a tiebreaker *within* a
group and never crosses region boundaries. Empty/absent config preserves prior behaviour
exactly. The probe is read-only (no switch, no exit IP-probe), so it runs under
`--dry-run` consistent with ADR-0003.

## Consequences

- "Must reach Telegram" is now expressible and enforced as a soft priority.
- Extra probes per cycle ≈ (alive nodes) × (required domains); acceptable at the default
  `main_interval`. Concurrency is left as a future optimisation.
- The selection invariants in CONTEXT.md gain a reachability dimension (documented there).
