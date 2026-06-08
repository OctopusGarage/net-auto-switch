# Contributing

Thanks for your interest in improving **net-auto-switch**! This is a small,
focused project — contributions of all sizes are welcome.

## Development setup

This project is managed with [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/OctopusGarage/net-auto-switch.git
cd net-auto-switch
uv sync                 # create .venv (Python pinned by .python-version) + install deps
```

Always run tools through `uv run` so they use the project's pinned interpreter
and locked dependencies — never the system Python.

## Before you open a PR

Run the full quality gate locally; CI runs the same checks:

```bash
uv run ruff check .          # lint
uv run ruff format --check . # format
uv run pytest                # tests
```

## Conventions

- **TDD** — write the failing test first; keep pure logic (selection, gating,
  classification) separate from I/O so it stays unit-testable.
- **Behavior-equivalence** — the selection / grouping algorithms are a faithful
  port of the original scripts. Don't change their behavior without recording an
  [ADR](docs/adr/).
- **No secrets** — never commit `config.toml` or any real secret / absolute home
  path. Only `config.example.toml` (with placeholder values) is tracked.
- **Domain language** — read [`CONTEXT.md`](CONTEXT.md) before changing behavior;
  it defines the layers, groups, and invariants.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`,
`fix:`, `docs:`, `build:`, `chore:`, `refactor:`, `test:`).

## Reporting issues

Open an issue with: macOS version, Clash Verge version, the relevant snippet of
`~/Library/Logs/net_auto_switch.log`, and steps to reproduce. Please redact your
Clash API secret and any subscription URLs.
