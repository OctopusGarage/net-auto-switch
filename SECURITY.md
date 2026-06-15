# Security Policy

## Supported versions

This is an actively developed single-maintainer project. Only the latest released
version receives security fixes.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's [Private Vulnerability Reporting](https://github.com/OctopusGarage/net-auto-switch/security/advisories/new)
(Security → Advisories → *Report a vulnerability*). Include reproduction steps and
the impact you observed. You can expect an initial response within about 7 days.

## Handling of secrets

This project never commits secrets:

- The real config (`config.toml`) is gitignored; only `config.example.toml`,
  which carries a placeholder secret, is tracked.
- Dataclass defaults in `config.py` use empty/placeholder values.
- A [gitleaks](https://github.com/gitleaks/gitleaks) scan runs in CI and in the
  local pre-commit hook (see `scripts/pre-commit`).

If you ever find a real secret or personal path committed to the repo, treat it as
a vulnerability and report it via the channel above.
