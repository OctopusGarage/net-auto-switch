# ADR-0007: Configurable region grouping

**Date:** 2026-06-08
**Status:** Accepted

## Context

Node grouping was hard-coded to `SG` / `Tokyo` / `JP_Other`: `classify_node`
used fixed `sg`/`jp`/`tokyo` regexes with `Tokyo` nested inside `JP`, and the
group set was literal. Config only let you tweak those four regexes and the
priority order — you could **not** add a region, so "prefer US nodes" was
impossible (US nodes classified as `None` and were never selected).

This contradicts [ADR-0002](0002-config-externalization-toml.md)'s goal of moving
tunables into config, and [ADR-0001](0001-layered-orchestration.md) notes the
selection algorithm should stay a faithful port — so any grouping change is
recorded here.

## Decision

Replace the fixed taxonomy with a config-driven, ordered `clash.regions` map
(name → regex); `group_priority` references those names. Classification returns
the **first** region whose regex matches (define specific regions first). The
selection algorithm itself is unchanged. The Tokyo-by-IP reclassification is
generalized to an optional `clash.ip_enrich = {target, source, match}` and
no-ops when its regions aren't present.

Defaults stay `SG` / `Tokyo` / `JP_Other` with the original regexes and the
Tokyo `ip_enrich`, and legacy `[clash.patterns]` configs are auto-translated, so
existing installs keep working.

## Consequences

- Any region taxonomy is now possible (e.g. `group_priority = ["US", "JP"]`).
  `load_config` validates that every `group_priority` entry is a defined region.
- **Minor behavior change:** the old code required a JP-name match before
  considering Tokyo; now a node literally named "Tokyo" (no JP marker) classifies
  as `Tokyo`. In practice real nodes carry region markers, and this is arguably
  more correct — accepted.
- `ClashConfig.patterns` / `ClashPatterns` are removed; code and tests use
  `regions` / `trial` / `ip_enrich`.
