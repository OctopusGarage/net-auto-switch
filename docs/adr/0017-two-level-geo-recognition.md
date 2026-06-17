# ADR-0017: Two-Level Geo Recognition and Offline Grouping

**Date:** 2026-06-17
**Status:** Accepted

## Context

[ADR-0007](0007-configurable-regions.md) replaced the hard-coded `SG` / `Tokyo` /
`JP_Other` trio with a config-driven `clash.regions` map (name → regex). This was
an improvement, but users still had to write regexes, maintain a flat
`group_priority` list, and know to put "Tokyo" before "JP_Other" to get the
one-city special-case. The Tokyo city group also depended on the `ip_enrich`
probe — a real `switch_proxy` PUT that made grouping an online operation and
broke the [ADR-0003](0003-dry-run-no-side-effects.md) side-effect contract under
`--dry-run`. As the user base grew across more countries, the config burden of
defining regexes for every country became impractical.

Design spec: `docs/superpowers/specs/2026-06-17-geo-region-recognition-design.md`.

## Decision

### 1. Built-in catalog replaces config-driven regions

A new `net_auto_switch/geo/` catalog ships recognition data for common countries
and major cities with all common spellings (ISO code, English, Chinese simplified
and traditional, flag emoji). `clash.regions` and its regex-writing requirement are
removed. Default grouping now covers all common countries — not just the original
three — superseding [ADR-0007](0007-configurable-regions.md)'s config-driven
`clash.regions`.

Users configure only:
- `clash.priority` — ordered list of country codes (e.g. `["SG", "JP", "US"]`).
- `[clash.cities]` — optional per-country city priority lists.
- `clash.region_overrides` — optional map to override or extend catalog entries.

No regex writing required.

### 2. Country → city two-level grouping with engine-derived downgrade chain

Group keys change from flat region names (e.g. `Tokyo`, `JP_Other`) to structured
keys: `country` (e.g. `JP`) or `country/city` (e.g. `JP/Tokyo`), with
`country/_other` for nodes in a country whose city is not recognized. The engine
derives a contiguous downgrade chain from `clash.priority` and `[clash.cities]`,
guaranteeing same-country city exhaustion before crossing to the next country —
city-stickiness no longer relies on the user ordering a flat list correctly.

The four selection invariants (healthy > trial, priority order, prefer current,
rate-limit switches) keep their semantics; only the grouping granularity changed.
The `Tokyo` city special-case is replaced by the general two-level mechanism.

### 3. Exit probe removed from the grouping path

The `ip_enrich` "switch to a node and probe its exit IP to fill the city group"
mechanism is removed. City is now recognized **by node name only** — GeoIP city
precision is unreliable and load-balanced exits vary; the entry/exit distinction
means only a real end-to-end request reveals the true exit city. Grouping is
therefore fully offline.

Consequences for related ADRs:

- **[ADR-0003](0003-dry-run-no-side-effects.md):** The dry-run special-case that
  skipped `enrich_tokyo_via_ip` is no longer needed — grouping never issues a
  network call.
- **[ADR-0012](0012-log-exit-operator-on-switch.md):** The exit probe survives
  only as the post-switch operator label (`get_exit_operator`). It is
  best-effort, runs after a real switch, and is never part of grouping.

### 4. Name-miss fallback: offline whois on the server address

When a node name does not match any catalog entry, `geo.by_whois.country_of_server`
performs an offline whois lookup on the server's address (entry-side) to infer the
country. This is an accepted trade-off: slightly less precise than probing the exit
IP, but fully offline and safe in dry-run. City is never inferred via whois.

Wiring this fallback live into `run_cycle` (requires reading the `server` field
from the subscription YAML) is deferred; the unit path is implemented and tested.
Recognition runs name-first today.

### 5. Config migration: expand → contract

New fields (`clash.priority`, `[clash.cities]`, `clash.region_overrides`) are
added additively; all consumers are migrated; legacy fields (`[clash.patterns]`,
`[clash.regions]`, `group_priority` with region names like `Tokyo` / `JP_Other`)
are removed from the schema but still load for backward compatibility.
`group_priority` region-name values are translated to country codes on load
(`Tokyo → JP`, `JP_Other → JP`, `SG → SG`), so existing installs continue
working without manual config edits.

## Consequences

- **No regex burden.** Users get sensible defaults for all common countries out of
  the box; advanced users can still override via `clash.region_overrides`.
- **Fully offline grouping.** No network calls in the classification path; dry-run
  is trivially side-effect-free.
- **City coverage is name-only.** Nodes whose names omit the city fall into
  `country/_other`. This is an accepted limitation — the alternative (probing every
  node's exit IP) reintroduced the side effects ADR-0003 prohibits.
- **Behavior change from ADR-0007:** `clash.regions` and its regex-based
  classification are gone. The three-region default (`SG` / `Tokyo` / `JP_Other`)
  expands to all common countries. Existing configs continue to work via the
  compatibility translation layer.
