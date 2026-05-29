# Project Principles

## Sensitive Data Isolation

Credentials, secrets, and machine-specific values must never be hardcoded.

1. **Never hardcode** secrets (the Clash API secret), absolute home paths, or live ports in source or docs.
2. **Use `config.toml`** — the real config is gitignored; only `config.example.toml` is tracked.
3. **Defaults are safe** — dataclass defaults in `config.py` use empty/placeholder values (e.g. `secret = ""`), never a real secret.

### Pre-commit check

```bash
grep -rn "your-clash-api-secret\|/Users/[a-z]\+/\|/home/[a-z]\+/" \
  --include="*.py" net_auto_switch/ tests/ || echo "✅ No secrets / personal paths found"
```

`config.example.toml` is the one intentional exception — it carries a placeholder secret.

## Process Management

The daemon is a single long-running process, identified by `net_auto_switch.cli` in its command line.

### Manual run (development)

```bash
./scripts/start.sh    # background; writes .net-auto-switch.pid
./scripts/status.sh   # is it running?
./scripts/stop.sh     # stop it
```

### Production (launchd — auto-start on boot, restart on crash)

```bash
./scripts/install-launchd.sh     # install deps + register + load
./scripts/uninstall-launchd.sh   # unload + remove
```

**Process-matching rule:** always include `net_auto_switch.cli` in `pgrep -f` patterns — never match bare `python`.

## Development Conventions

This project is managed with **uv**. Always run tools through `uv run` so they use the
project's pinned interpreter (`.python-version`) and locked deps (`uv.lock`) — never the
system / conda python (using the wrong interpreter is what broke the launchd agent once).

- `uv sync` — create / update `.venv` from `pyproject.toml` + `uv.lock`.
- `uv run pytest` — run the full suite (configured in `pyproject.toml`).
- `uv run ruff check .` / `uv run ruff format .` — lint & format.
- `uv add <pkg>` / `uv add --dev <pkg>` — add a runtime / dev dependency.
- **TDD** — write the failing test first; keep pure logic (selection, gating, classification) separate from I/O so it stays unit-testable.
- **Behavior-equivalence** — the selection/grouping algorithms are a faithful port of the original scripts. Don't change them without recording an ADR.

## Domain docs

- `CONTEXT.md` — domain glossary (layers, groups, invariants). Read it before changing behavior.
- `docs/adr/` — architecture decisions. If a change contradicts an ADR, surface it explicitly rather than silently overriding.
