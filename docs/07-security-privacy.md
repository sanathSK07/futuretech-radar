# 07 — Security and Privacy

**Status:** Phase 1 · **Last updated:** 2026-09-17 · **Owner:** SK

Covers section L. Written as a threat model plus concrete controls, because "security awareness" in a portfolio is demonstrated by a threat model that names attack surfaces and shows the mitigations in code, not by a list of buzzwords.

---

## L.1 Assets and trust boundaries

| Asset | Why it matters |
| --- | --- |
| Curator decisions (`review_action`, confirmed assessments) | Irreplaceable; the product's credibility |
| API keys (Anthropic, OpenAlex, Semantic Scholar, PatentsView later) | Cost exposure; abuse |
| Admin token | Full write access to public content |
| Public integrity of records | A defaced technology page destroys trust |
| Database availability | Free-tier limits are easy to exhaust |

Trust boundaries: (1) the Internet → fetchers (untrusted content in); (2) fetched content → LLM (prompt-injection surface); (3) public Internet → API (read) and → admin API (write); (4) GitHub Actions → database (secrets in CI); (5) Vercel → API.

## L.2 Threat model (STRIDE, MVP scope)

| Threat | Vector | Likelihood | Impact | Controls |
| --- | --- | --- | --- | --- |
| **Spoofing** — forged admin | Stolen or guessed admin token | Low–Med | High | 256-bit random token in env only; constant-time compare; rotation procedure; admin routes rate-limited and logged; Phase 4 replaces with proper auth |
| **Tampering** — poisoned source | A compromised or malicious feed injects fabricated claims | Med | High | Sources are allow-listed in `sources.yaml` via PR; tier caps what a source can support; human gate for ≥ M4 and featured; every claim links to its source so tampering is visible |
| **Tampering** — prompt injection | Fetched text instructs the model to alter output | Med | Med | Model has no tools; structured-output schema; quote verification; injection test corpus in CI; content delimiters; outputs are proposals only |
| **Tampering** — SSRF via fetchers | A feed link points at internal or metadata endpoints | Med | Med–High | Fetcher resolves DNS and rejects private/link-local/loopback ranges *after* resolution; only `http(s)`; redirects re-validated; per-host allow-list for non-feed fetches; timeouts; size caps (5 MB) |
| **Tampering** — malicious content | Zip bombs, decompression bombs, malformed XML/HTML | Med | Med | Streaming size limits; `defusedxml`; HTML sanitised with an allow-list before storage; never render fetched HTML |
| **Repudiation** | Untraceable edits | Low | Med | Every write carries `analysis_run_id` or `review_action_id`; append-only versions |
| **Information disclosure** | Secrets in logs or repo; verbose errors | Med | High | `.env` git-ignored; `.env.example` only; secret scanning (GitHub push protection); structlog redaction; generic 5xx bodies; CSP/HSTS headers |
| **Information disclosure** — PII | Author names from papers | Low | Low–Med | Authors stored as metadata for attribution only; no person entity pages in MVP; no user accounts; no analytics cookies |
| **Denial of service** | Scrapers hammer search; expensive vector queries | Med | Med | Per-IP rate limits (slowapi); query cost caps (limit + timeout); edge caching of public pages; Neon scale-to-zero means cold starts, not bills |
| **Denial of wallet** | Pipeline loops or oversized documents burn LLM budget | Med | High | Hard daily cost cap in `analysis_run` accounting; job aborts at cap; per-document token cap; Batch API for bulk; alert |
| **Elevation of privilege** | Admin endpoints exposed without auth by mistake | Low | High | Admin router mounted under `/admin` with a dependency that fails closed; integration test asserts 401 on every admin route without token |
| **Supply chain** | Malicious dependency | Low–Med | High | `uv.lock`/`package-lock` committed; Dependabot; `pip-audit` + `npm audit` in CI; pinned GitHub Actions by SHA; minimal base images |
| **Data licence violation** | Serving full text we may not redistribute | Med | Med (legal/reputational) | Licence field per document; `content_text` cleared post-extraction where required; UI shows excerpts + links only |

## L.3 Secure defaults (implementation checklist)

- All configuration via environment (`pydantic-settings`); startup fails if required secrets are missing or the admin token is shorter than 32 bytes.
- FastAPI: CORS restricted to the web origin; security headers middleware (CSP, HSTS, X-Content-Type-Options, Referrer-Policy); request body size limit; uniform error handler.
- SQL only through SQLAlchemy; no string-built queries; FTS inputs passed as parameters (`plainto_tsquery`/`websearch_to_tsquery`).
- Next.js: server components fetch the API with a server-side base URL; no admin token ever shipped to the browser; the review UI calls admin routes through a Next.js route handler that injects the token from server env after checking a session cookie set by a simple login page (MVP: single password → signed, `HttpOnly`, `SameSite=Lax` cookie, 12-hour expiry). The login route is rate-limited (5 attempts / 15 min / IP) and every attempt is logged; the password is compared in constant time against an Argon2 hash from env.
- GitHub Actions: secrets scoped to the ingest workflow; `permissions: contents: read`; third-party actions pinned; no secrets in `workflow_dispatch` inputs.
- Backups encrypted at rest (R2/S3 default) and restore tested.
- Logging never includes document full text or secrets; run IDs correlate logs.

## L.4 Privacy

- No user accounts, tracking, or third-party analytics in the MVP. Server access logs are retained 30 days.
- Author names appear only as bibliographic metadata, as they do in the source. No profiles, no aggregation across papers, no contact details.
- Corrections go through GitHub Issues (pre-filled template); the platform stores no correspondence and no emails.
- Data published under CC-BY 4.0 excludes operational logs.
- Relevant law: Canada's PIPEDA applies weakly given no personal data is collected beyond public bibliographic metadata and optional correction emails; the design keeps it that way.

## L.5 Responsible-AI controls (summary; details in `04-ai-analysis-framework.md`)

Proposals not publications; quote-grounded extraction; no entity creation by the model; model and prompt version on every output; human gate on high-stakes fields; visible "AI-proposed, unreviewed" badge; evaluation set in CI; injection test corpus.

## L.6 Phase 3 security validation

`pip-audit`, `npm audit`, `bandit`, `semgrep` (OSS rules) in CI; OWASP ZAP baseline scan against the deployed site; manual SSRF test cases (localhost, 169.254.169.254, DNS rebinding to private IP, redirect to file://); admin route enumeration test; token rotation drill; restore-from-backup drill; a short written security review in `docs/reviews/phase3-security.md`.
