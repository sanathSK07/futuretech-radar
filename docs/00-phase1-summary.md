# 00 — Phase 1 Summary and MVP Recommendation

**Status:** Phase 1 complete · **Date:** 2026-09-17 · **Owner:** SK

## The recommendation in five lines

1. Build the MVP around one interaction: a maturity stage a sceptic can click through to dated, quoted, tiered evidence. Everything else is secondary.
2. Scope: six domains, ~30 curated technologies, daily batch ingestion from arXiv, bioRxiv, OpenAlex and ~40 official feeds.
3. Stack: Python (FastAPI, SQLAlchemy, Pydantic) + Next.js 15/TypeScript; PostgreSQL 16 with pgvector on Neon; pipeline scheduled in GitHub Actions; Claude Haiku 4.5 / Sonnet 5 via structured outputs and the Batch API. Projected AI cost ≈ $14/month; hosting on free tiers.
4. Timeline: five two-week sprints from 2026-09-22 to 2026-11-27 at ~8 h/week, then a two-week validation phase before exams.
5. Credibility mechanisms, not features, are the portfolio value: claim-level provenance with verified quotes, an evidence-typed maturity rubric, a human review gate, an evaluation set in CI, and open data.

## What changed from the original brief, and why

| Brief said | Recommendation | Reason |
| --- | --- | --- |
| Track ~28 technology areas | Six deep, rest by configuration after Phase 3 | Source coverage, review burden and 80 hours of build time |
| 20 analysis questions per development | Stored as claim types and structured fields; not all 20 answered per record | Most primary sources answer 5–8 of them; forcing 20 produces filler. The schema supports all 20; the UI shows what has evidence and marks the rest "not assessed" |
| Importance score with quantitative dimensions | Six ordinal ratings with rationale and evidence; no composite | Avoids false precision; composite requires an ADR that defines measurement and uncertainty |
| One maturity stage per technology | Stage per narrowly scoped capability; domains show distributions | "Quantum computing" spans M1–M6 depending on the application |
| Organisation tracking incl. investments, researchers | Organisations by ROR ID with developments and technologies; no funding data, no people entities in MVP | Funding is paid data and not maturity evidence; people are a privacy and entity-resolution burden |
| Auth/authorisation | Single admin token + session cookie for the curator; anonymous public reads | One user; auth is Phase 4 |
| Graphs, trends, alerts, reports, Q&A | Phase 4, one per month, each behind an ADR; schema supports them from day one | The brief's own staged-build instruction |
| Realistic timeframes | Never model-generated; only source-reported, expert, or curator scenario, each labelled | Anti-hallucination |

## Self-review of this Phase 1 work

**Assumptions made:** that arXiv, bioRxiv, OpenAlex and official feeds give enough T1/T2 coverage for six domains (weak for semiconductors and batteries — now called out as R15 and mitigated with OpenAlex discovery); that quote verification is the main hallucination control (true for fabrication, not for misinterpretation — eval set covers that); that ~100 triaged documents/day suffices (unvalidated, A1); that SK can curate ~30 min/day (Q4).

**What could be wrong:** the maturity rubric may under-stage domains where artefacts are rare (robotics) — domain-specific evidence notes are a Sprint 2 task; the 80-hour estimate is optimistic — the cut list in `05` is explicit; the cost model depends on abstract-level extraction — A9 tests it.

**Evidence missing:** no user interviews (personas are hypotheses); no verified primary sources yet for seed technologies; competitor pricing for gated products unverified.

**Unnecessary features removed during review:** semantic search ranking (kept for dedup only), a corrections form with stored emails (replaced by GitHub Issues), a cost dashboard (CLI report), the `document_chunk` table (one vector per document), Semantic Scholar enrichment (Phase 4).

**Scale failure points:** curator queue (R14); Neon storage (R7); staleness computed at read time (fine until ~10⁵ records).

**Security:** STRIDE table in `07`; the notable additions in review were login rate limiting and Argon2 hashing for the curator login, and removing the corrections form's spam and PII surface.

**AI hallucination points:** entity creation (blocked), dates (basis required), numbers (must be quoted), stage evidence pointers (validated), summaries (labelled and marked unsupported when uncited).

**Staleness:** windows per stage; confidence downgrade; visible "last evidence" date.

**What a senior engineer would criticise:** two deployables for a solo project (accepted for portfolio breadth; ADR-0001); Must-have count (cut in review); no load numbers (Phase 3 measures them).

**What makes it stronger as a portfolio project:** publish the rubric, the eval numbers and the dataset; make "Why?" the hero interaction; write the README around the evidence model.

## First three actions (Sprint 0, starting 2026-09-22)

1. Create the public repo `futuretech-radar`; commit this `docs/` set, `PROJECT-STATUS.md`, `LICENSE`, `DATA-LICENSE`; enable secret scanning and Dependabot. (~1 h)
2. `infra/docker-compose.yml` with Postgres 16 + pgvector; `packages/core` with `pyproject`, settings, SQLAlchemy models for `source`, `fetch_run`, `source_document`; first Alembic migration; CI running ruff + mypy + pytest. (~4 h)
3. `sources.yaml` with arXiv categories for the six domains and ten official feeds; `radar ingest --since 1d` fetching arXiv via RSS/API with the 3-second limiter and writing `source_document` rows idempotently; a test proving a re-run inserts zero duplicates. (~4 h)

Done means: real documents in the database from a scheduled GitHub Actions run by 2026-09-29.
