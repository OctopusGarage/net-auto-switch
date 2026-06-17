# ADR-0018: Node Blacklist (CN/HK + Chinese-cloud Hard-Exclude)

**Date:** 2026-06-17
**Status:** Accepted

## Context

The auto-switch daemon selects proxy nodes by latency and region priority but has no
mechanism to exclude nodes whose traffic passes through China or Hong Kong, or whose
infrastructure is operated by a Chinese cloud provider (腾讯云, 阿里云, 华为云, …).
Users who need to avoid such nodes currently cannot do so without manual intervention.

[ADR-0017](0017-two-level-geo-recognition.md) established that grouping is fully
offline (name-only classification) and that the exit IP probe is restricted to a
best-effort post-switch operator label (ADR-0012), never part of grouping. A
blacklist feature re-introduces whois lookups for exclusion purposes, requiring a
scoped exception to that decision.

Design spec: `docs/superpowers/specs/2026-06-17-node-blacklist-design.md`.

## Decision

### 1. Feature is opt-in via `[clash.blacklist]`

```toml
[clash.blacklist]
countries  = ["CN", "HK"]
operators  = ["腾讯云", "阿里云", "华为云"]
relearn_days = 7
```

Absent or empty `countries` + `operators` → feature off; current behaviour is
unchanged. `ClashConfig.blacklist` defaults to `{}`.

### 2. Tier 1 — offline pre-filter (every cycle, hard-exclude)

Before the four-invariant selection algorithm runs, every node is tested:

1. Name-recognized country ∈ `blacklist.countries` → exclude.
2. Entry-side whois country ∈ `blacklist.countries` → exclude.
3. Entry-side whois operator label contains any `blacklist.operators` string
   (substring, case-insensitive) → exclude.
4. Node appears in the learned exit-blacklist (Tier 2) and has not expired → exclude.

Entry-whois is resolved from the node's `server` address and cached per server for
the lifetime of the controller. No node switching occurs → Tier 1 is safe in
dry-run and fully offline.

### 3. Tier 2 — learned exit-blacklist (post-switch only)

`run_cycle` already probes the exit operator after a real switch for the
notification label (ADR-0012). This probe is extended:

- Parse exit `(country, operator)` via `exit_label_from_ipwhois`.
- If exit country ∈ `blacklist.countries` or operator matches `blacklist.operators`
  → record the node in the learned blacklist and re-select the next candidate,
  switching again.
- Re-selection is bounded by the existing `max_switch_per_min` rate limit and a
  hard cap of five retries to prevent loops when all reachable exits are bad.
- Tier 2 runs **only after a real switch** and is **skipped in dry-run** (ADR-0003).

### 4. Scoped exception to ADR-0017's offline-only rule

ADR-0017 removed exit probing from the grouping path and declared grouping fully
offline. The blacklist is not part of grouping; it is a pre-filter applied before
the selection algorithm. The scoped exception is:

- **Entry whois** is used in Tier 1 (offline + cached per server, same as
  ADR-0017's name-miss whois fallback). It is skipped entirely when the blacklist
  feature is disabled.
- **Exit probe** is used in Tier 2 only — post-switch, never dry-run — reusing the
  probe already present for ADR-0012. It is not in the grouping path and does not
  affect any selection invariant.

### 5. Learned blacklist persistence

- File: `<config-dir>/blacklist.json` (same directory as the loaded `config.toml`).
- Shape: `{ "<node name>": "<ISO-8601 timestamp>" }`.
- An entry is active while `now − ts < relearn_days`; expired entries are ignored
  and pruned on the next write, so a node is eventually re-verified (its exit may
  rotate to a different host).
- Loaded once per controller start; updated in-place when Tier 2 records a bad node.

### 6. CLI commands

`net-auto-switch blacklist list` — print learned entries with their age and expiry.
`net-auto-switch blacklist clear` — delete `blacklist.json`.

### 7. Selection invariants are unchanged

Blacklisting only removes candidates. The four invariants
(stability-first, current-group-first, priority-downgrade, no-usable-node → no-switch)
are applied to whatever candidates remain after the pre-filter. A fully-blacklisted
group is simply empty; a fully-blacklisted node set produces the same "no usable
node" outcome as today.

## Consequences

- **Opt-in, zero cost when off.** No whois lookups, no file I/O, no behaviour
  change when `[clash.blacklist]` is absent or has empty lists.
- **Entry whois re-enters the path** for Tier 1, as a scoped exception to
  ADR-0017. It is offline+cached, never blocks a cycle, and is gated on the feature
  being enabled.
- **Exit probe remains post-switch only.** Tier 2 does not change the grouping or
  selection algorithm; it merely records a learned fact and triggers one additional
  switch, bounded by existing rate limits.
- **Dry-run safety preserved.** Tier 1 is read-only; Tier 2 is skipped entirely in
  dry-run (ADR-0003 contract unchanged).
- **Learned entries expire.** A node is re-verified after `relearn_days` days, so
  infrastructure migrations are handled automatically without manual cache clearing.
- **Behavior change vs. today:** CN/HK/Chinese-cloud nodes are excluded when the
  feature is enabled. The all-blacklisted edge case produces a no-switch outcome,
  consistent with existing behaviour for all-dead nodes.
