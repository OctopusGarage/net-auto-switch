# ADR-0001: Layered WiFi + Clash Orchestration

**Date:** 2026-05-29
**Status:** Accepted

## Context

Two independent scripts existed: one switched WiFi by ping quality, one switched
Clash Verge nodes by latency. Run separately they had duplicated loops, separate
configs, and no shared logging. The physical network (WiFi) sits below the proxy
layer (Clash) — fixing a bad proxy is pointless when the underlying WiFi is the
problem.

## Decision

Merge them into a single daemon with one main loop. Each cycle runs **WiFi first,
then Clash**:

- WiFi is optional (`wifi.enabled`) and low-frequency (`check_interval` plus a
  post-switch `switch_cooldown`), because changing WiFi is disruptive and should
  be rare.
- Clash runs every cycle (`main_interval`) because node quality fluctuates and
  switching nodes is cheap.

`orchestrator.py` owns scheduling; `wifi.py` and `clash.py` own their layer's
mechanics and know nothing about each other.

## Consequences

- One config, one logger, one launchd service.
- Each layer is independently testable (pure gating / selection functions).
- A failure in one layer is caught and isolated — the other layer still runs and
  the daemon survives.
- WiFi cadence and Clash cadence are decoupled even though they share the loop.
