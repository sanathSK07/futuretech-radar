# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private vulnerability reporting on this repository ("Security" tab → "Report a vulnerability"). You should receive an acknowledgement within 7 days.

## Scope

- The ingestion pipeline (untrusted web content in; SSRF, decompression, prompt-injection surfaces)
- The API (read and admin routes)
- The web app (curator login, review queue)
- CI workflows and secrets handling

The threat model and controls are documented in [`docs/07-security-privacy.md`](docs/07-security-privacy.md).

## Practices

- Secrets live only in environment variables and GitHub Actions secrets; `.env` is git-ignored and GitHub push protection is enabled.
- Dependencies are pinned via lockfiles and monitored by Dependabot; `pip-audit` and `npm audit` run in CI.
- Third-party GitHub Actions are pinned to commit SHAs.
- Fetched content is treated as data: the analysis model has no tools, outputs are schema-constrained, and every extracted claim must be a verified quote from its source.
