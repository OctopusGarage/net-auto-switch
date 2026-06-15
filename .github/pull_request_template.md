## Summary

<!-- What does this change and why? -->

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy net_auto_switch` passes
- [ ] `uv run pytest` passes (added/updated tests where it makes sense)
- [ ] `shellcheck` passes for any changed shell scripts
- [ ] No secrets or personal paths committed (gitleaks pre-commit hook installed)
- [ ] Behavior changes that touch selection/grouping are recorded in `docs/adr/`
