# ADR-0012: Log the Exit Operator on a Real Node Switch

**Date:** 2026-06-15
**Status:** Accepted

## Context

When the daemon switches to a new Clash node the log only named the node
(`Switched to <node>`). Operators want to know *where that node egresses* — which
cloud / ISP owns the exit IP (AWS, 腾讯云, Cloudflare, …) — to judge whether the
new node is sensible. The standalone `whois` lookup (see `net_auto_switch/whois.py`,
ported from `k_whois`) already maps a free-text isp/org blob to a friendly operator
label via `OPERATOR_HINTS`.

## Decision

After a **successful, non-dry-run** `switch_proxy`, `run_cycle` calls
`ClashController.get_exit_operator()` and appends the result to the switch log line,
e.g. `Switched to JP-Tokyo-03 (exit: AWS (US))`.

`get_exit_operator` reuses the existing ipwhois.app probe through the local proxy
(the same plumbing `get_node_region` uses), reads its `isp`/`org`/`country_code`,
and maps them through `whois.match_operator`. It is **best-effort**: any failure
returns `""` and the switch log simply omits the suffix — the switch itself is never
affected.

It is deliberately **not** a full `whois` subprocess: the daemon stays on one cheap
HTTP call per switch instead of forking `dig`/`whois` in the hot path.

## Consequences

- The probe is an IP-egress side effect, so it runs **only after a real switch** and
  **never under `--dry-run`** — preserving the ADR-0003 contract. Switches are
  rate-limited (`max_switch_per_min`), so the added I/O is bounded.
- Depends on ipwhois.app being reachable through the proxy; when it isn't, the label
  is silently dropped (non-fatal).
- The selection / grouping algorithm is unchanged — this is logging enrichment only.
