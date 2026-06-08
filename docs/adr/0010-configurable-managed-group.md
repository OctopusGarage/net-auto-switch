# ADR-0010: Mode-aware managed proxy group

**Date:** 2026-06-08
**Status:** Accepted

## Context

`ClashController` hard-coded the `GLOBAL` proxy group in both directions: it read
the "current node" from `proxies["GLOBAL"]["now"]` and wrote switches to
`PUT /proxies/GLOBAL`. But which group actually carries traffic depends on Clash's
**Proxy Mode**:

- **global** — all traffic flows through `GLOBAL`.
- **rule** — traffic follows rules into named selector groups (commonly `Proxy`);
  `GLOBAL`'s selection is inert.
- **direct** — everything bypasses proxies; no group selection matters.

This produced a silent failure on a live install (rule mode): `GLOBAL` happened to
point at a healthy Tokyo node (~83ms) while the `Proxy` group routing 62/68 active
connections was stuck on a dead node (`日本-TY-2`, 9999ms). Every cycle the daemon
read the healthy `GLOBAL` node, logged "No switch needed", and never touched the
group actually carrying traffic.

A fixed group (whether hard-coded or configured) is fragile: it breaks whenever the
user changes mode. The correct group is a function of the live mode, so it should be
resolved at runtime, not pinned.

[ADR-0001](0001-layered-orchestration.md) flags the selection algorithm as a
faithful port, so changing which group it acts on is recorded here.

## Decision

Resolve the managed group **per cycle** from the live Clash mode (`GET /configs`):

- **global** → manage `GLOBAL`.
- **direct** → skip the cycle entirely (nothing to switch).
- **rule** → manage the busiest *entry group* among live connections
  (`GET /connections`): each connection's `chains` is node-first, entry-group-last,
  so the last element is the group the rules routed it through. The most common
  Selector entry group wins. If none can be detected (e.g. no active connections),
  fall back to `GLOBAL` with a warning so the daemon still acts.

`switch_proxy(node, group)` is now a dumb primitive taking an explicit group; the
read, the IP-enrichment probe, and the switch all use the resolved group. The
selection/grouping algorithm itself is unchanged.

`clash.managed_group` defaults to `"auto"` (the resolution above). Setting it to a
literal group name forces that group unconditionally — an escape hatch for
non-standard setups (multiple rule groups, scripted routing). A missing resolved
group is logged with the available selectors and skips the cycle rather than
crashing on `KeyError` (which under launchd `KeepAlive` would be a restart loop).

## Consequences

- Works across mode changes without reconfiguration: global installs keep managing
  `GLOBAL` exactly as before; rule installs now manage the group traffic actually
  uses — the fix for the silent "abnormal node, no switch" failure.
- Two extra read-only API calls per cycle in `auto` mode (`/configs`,
  `/connections`); negligible at the 10-minute cadence, and skipped when an explicit
  group is configured.
- **Rule-mode caveat:** Clash exposes no single canonical "the rule group", so the
  busiest entry group is inferred from live traffic. With no active connections the
  signal is absent and we fall back to `GLOBAL` (logged). Nested selectors
  (`Proxy → URLTest → node`) resolve to the outermost Selector; if that group can't
  hold the chosen leaf node, the switch `PUT` fails and is logged as before.
- `get_node_region` / `enrich_via_ip` now probe through the resolved group,
  consistent with how traffic is actually routed.
