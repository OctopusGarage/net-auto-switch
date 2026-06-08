# ADR-0008: Wizard detects regions from the live subscription

**Date:** 2026-06-08
**Status:** Accepted

## Context

[ADR-0007](0007-configurable-regions.md) made regions configurable, but the
`init` wizard ([ADR-0005](0005-guided-setup-wizard.md)) still only previewed the
three default groups and let you reorder those. A user couldn't discover that
their subscription actually has US / HK / TW / … nodes, so configuring a
non-default priority still meant editing TOML by hand.

## Decision

The wizard now fetches the live node list from the Clash API and matches names
against a built-in `REGION_CATALOG` (Tokyo, JP, SG, HK, TW, US, KR, UK, DE),
showing each region with its node count (sorted by count). The user picks the
priority order (or accepts all detected, most-common first); `init` writes a
matching `[clash.regions]` and `group_priority`. `--yes` accepts all detected.

`detect_regions()` is a pure, tested function. Generated `regions` are emitted in
catalog order (specific-first, e.g. Tokyo before JP) so first-match
classification stays correct regardless of the chosen priority order.

## Consequences

- New users get a config tuned to what their subscription actually contains,
  without knowing the region names up front.
- Region detection is best-effort: if the API is unreachable, the wizard falls
  back to the default SG / Tokyo / JP_Other regions.
- The catalog is a fixed starter set; exotic regions still need a manual
  `[clash.regions]` entry (the wizard warns about unknown names it's given).
