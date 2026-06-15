# ADR-0004: Use uv for Environment & Dependency Management

**Date:** 2026-05-29
**Status:** Accepted

## Context

The project was first installed with `pip install -e` against whatever `python3`
the shell resolved to (here, a conda interpreter). When registered as a launchd
agent, the wrapper called a bare `python3` resolved against launchd's own `PATH`
(`/opt/homebrew/bin:…`), which pointed at a *different* interpreter that did not
have the dependencies installed — the daemon crash-looped with
`ModuleNotFoundError: No module named 'requests'`.

The root cause is an unpinned, ambiguous interpreter. We need a reproducible
environment whose interpreter and dependency versions are fixed and independent
of whatever Python happens to be on `PATH`.

## Decision

Manage the project with [uv](https://docs.astral.sh/uv/):

- `.python-version` pins the interpreter (3.12); uv provisions a managed CPython,
  so it does not depend on system / homebrew / conda Python.
- `uv sync` creates `.venv` and installs from a committed `uv.lock` (reproducible).
- Dev tools live in a PEP 735 `[dependency-groups] dev` group.
- All entry points use the **absolute** venv interpreter `.venv/bin/python`:
  - the launchd wrapper execs `$PROJECT/.venv/bin/python -m net_auto_switch.cli`,
  - `scripts/start.sh` runs `uv sync` then the same venv python,
  - `install-launchd.sh` runs `uv sync` instead of `pip install`.

## Consequences

- The launchd interpreter mismatch is structurally impossible — the wrapper points
  at one specific, dependency-complete interpreter.
- Environments are reproducible across machines via `uv.lock` + `.python-version`.
- Contributors must have `uv` installed; all commands go through `uv run`.
- `.venv/` stays gitignored; `uv.lock` and `.python-version` are committed.
