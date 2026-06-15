# ADR-0009: Health-check gate in `init`, and no auto subscription update

**Date:** 2026-06-08
**Status:** Accepted

## Context

Before finishing setup we want to confirm the subscription actually has working
nodes, and ideally fix it when it doesn't (refresh the subscription, pick a
working profile). We investigated what the local APIs really allow.

Findings (verified against a live Clash Verge Rev v1.19.17):

- **Node health & selection — reliable.** The mihomo core API exposes
  `GET /group/{name}/delay`, a concurrent delay test (≈2s for a whole group), and
  per-node `/proxies/{n}/delay` + `PUT /proxies/{n}` to select. Already used.
- **Subscription update — not reliably automatable.** `GET /providers/proxies`
  shows the subscriptions as `vehicleType: Compatible` (inline, no URL), not
  `HTTP` proxy-providers, so `PUT /providers/proxies/{name}` can't re-fetch them.
  Clash Verge performs subscription updates in-app with no stable public API; the
  only automation paths are brittle AppleScript UI clicking (same fragility as
  the profile-switch fallback) or re-downloading the URL ourselves and rewriting
  Clash Verge's files (risks corrupting its state). Neither is robust.

## Decision

Add a **health-check gate** to `init`: after the API probe, call
`GET /group/GLOBAL/delay` and report `reachable/total`. If zero are reachable,
print actionable guidance (update the subscription in Clash Verge / check expiry)
and abort in interactive mode (continue under `--yes`). The check is best-effort:
if the endpoint is unavailable it's skipped, not fatal.

**Do not** auto-trigger subscription updates or profile switches in `init` — no
reliable API exists for Clash Verge's inline subscriptions. The correct durable
fix is Clash Verge's own per-profile auto-update interval.

## Consequences

- Setup fails fast with a clear cause when the subscription is dead, instead of
  installing a daemon that can't do anything.
- We deliberately accept that subscription refresh stays a manual Clash Verge
  action; revisit only if Clash Verge exposes a stable update API or users adopt
  HTTP proxy-providers.
