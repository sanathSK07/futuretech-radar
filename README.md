# FutureTech Radar

**An evidence-graded intelligence platform for emerging technologies.** It tracks developments from universities, labs, companies and public research organisations, and answers one question a news feed cannot: *how real is this, and what is the evidence?*

> Status: **Phase 2 (MVP), Sprint 0 complete.** Ingestion runs: the schema, the source registry and the arXiv fetcher are in place and tested. Claim extraction and the web app land in Sprints 1–3. See [`PROJECT-STATUS.md`](PROJECT-STATUS.md).

## What makes it different

Most technology-intelligence tools optimise for volume (aggregators), opinion (analyst radars) or paper discovery (academic search). None of them shows the evidence behind a maturity judgement. FutureTech Radar is built around four mechanisms that make its claims inspectable:

1. **The claim is the atomic unit.** Every fact in the system is one assertion with a verbatim quote (verified in code to exist in the source), a claim type (measured result, demonstration, deployment, regulatory event, self-reported claim, expectation, forecast, opinion), a date with its basis, and a source tier.
2. **Maturity is evidence-typed, not vibes-typed.** Nine stages (M0 speculative → M8 mature) each define the evidence required to enter them. Developer-controlled evidence caps a technology at M3; M4 and above need a different organisation's measurement, a third-party observation, a named pilot, or a regulatory event. Stage and confidence are separate, and "insufficient evidence" is a displayed state.
3. **AI proposes; evidence and humans decide.** Models extract claims and propose stages, but must cite claim IDs per criterion, never create organisations or technologies, and never generate timeframes. Every output records model ID, prompt version and inputs. Stages M4+ and featured technologies require human confirmation; lower stages publish with an "AI-proposed, unreviewed" badge.
4. **Evaluation in CI.** A labelled set measures extraction precision, claim-type accuracy, stage agreement and dedup quality; a prompt change that regresses the numbers blocks the merge.

Forecasts are never presented as facts. Every dated statement carries one of five labels: observed fact, source-reported expectation, expert forecast, model inference, or curator scenario.

## Scope of the MVP

Six domains, ~30 curated technologies, daily batch ingestion from arXiv, bioRxiv, OpenAlex and ~40 official feeds, organisations resolved to ROR IDs. Sprint 0 ships the arXiv fetcher across all six domains; the rest follow.

| Domain | Examples of tracked capabilities |
| --- | --- |
| AI / ML / agents | Long-horizon agents; mechanistic interpretability; generative coding |
| Robotics & humanoids | General-purpose manipulation; humanoid locomotion in unstructured environments |
| Quantum computing | Below-threshold error correction; useful-scale fault tolerance |
| Semiconductors & advanced computing | Backside power delivery; chiplet interconnect; photonic compute |
| Energy | Compact tokamak fusion; sodium-ion batteries; small modular reactors |
| Biotech & synthetic biology | Bespoke base-editing therapies; cell-free protein synthesis |

Remaining domains from the original brief (cybersecurity, space, materials, BCI, photonics, climate, agtech and others) are added by configuration after the MVP is validated.

## Architecture at a glance

```
Sources (arXiv · bioRxiv · OpenAlex · official feeds · ROR)
        │  daily, GitHub Actions
        ▼
Pipeline (Python): fetch → normalise → dedupe → triage → extract claims → resolve entities → propose stage & relations
        │  proposals only
        ▼
PostgreSQL 16 + pgvector (Neon)  ◄──  Curator review queue (accept / edit / reject, fully logged)
        │
        ▼
FastAPI (read + admin API)  ──►  Next.js web app (dashboard · explorer · technology · organisation · search · "Why?")
```

Python 3.12 (FastAPI, SQLAlchemy 2, Pydantic v2), Next.js 15 / TypeScript, PostgreSQL with pgvector and full-text search as the only datastore, local sentence-transformer embeddings, Claude via structured outputs and the Batch API. Projected AI cost ≈ $14/month; hosting on free tiers. Rationale and alternatives are in [`docs/decisions/`](docs/decisions/).

## Documentation

| Doc | Contents |
| --- | --- |
| [`docs/00-phase1-summary.md`](docs/00-phase1-summary.md) | Executive summary, MVP recommendation, self-review, first actions |
| [`docs/01-problem-market-users.md`](docs/01-problem-market-users.md) | Problem, competitor analysis, personas, use cases |
| [`docs/02-research-methodology-and-sources.md`](docs/02-research-methodology-and-sources.md) | Units of analysis, source tiers, claim types, evidence ladder, verified data sources, licensing |
| [`docs/03-maturity-and-impact-frameworks.md`](docs/03-maturity-and-impact-frameworks.md) | The M0–M8 maturity model with required evidence; importance without a composite score |
| [`docs/04-ai-analysis-framework.md`](docs/04-ai-analysis-framework.md) | Pipeline contracts, grounding rules, traceability, evaluation, cost model |
| [`docs/05-mvp-and-roadmap.md`](docs/05-mvp-and-roadmap.md) | MoSCoW features, seed plan, sprints, validation checklist |
| [`docs/06-architecture-stack-data.md`](docs/06-architecture-stack-data.md) | Stack, architecture views, ingestion, citations, backup, schema v0 |
| [`docs/07-security-privacy.md`](docs/07-security-privacy.md) | Threat model (STRIDE), secure defaults, privacy |
| [`docs/08-risks-and-open-questions.md`](docs/08-risks-and-open-questions.md) | Ranked risks, open decisions, assumptions to validate |
| [`docs/decisions/`](docs/decisions/) | Architecture decision records |

## Roadmap

| Phase | Window | Outcome |
| --- | --- | --- |
| 1 Research & specification | Sep 2026 | Done — this document set |
| 2 MVP | Sep 22 – Nov 27, 2026 | Ingestion, grounded extraction, maturity proposals, review queue, public site |
| 3 Validation | Nov 30 – Dec 11, 2026 | Published evaluation metrics, security checklist, usability sessions |
| 4 Advanced | Jan – Apr 2027 | Relationship graph, trends, alerts, Q&A over claims |

## Running it

Requires [uv](https://docs.astral.sh/uv/) and a PostgreSQL 16+ with pgvector.
Docker is the easy path; any hosted PostgreSQL with the `vector` extension works
too — put its URL in `RADAR_DATABASE_URL` and a *separate* database in
`RADAR_TEST_DATABASE_URL`, because the test suite drops and rebuilds its schema
on every run.

```bash
make setup        # virtualenv, dependencies, .env from .env.example
make db-up        # optional: PostgreSQL 16 + pgvector on localhost:5433, via Docker
make migrate      # apply migrations
make check        # lint, strict type check, tests

make sources      # show the source registry
make smoke-arxiv  # one live arXiv request, prints what was parsed, writes nothing
make ingest       # ingest the last day from every active source
```

Secrets go into `.env` through a hidden prompt, never through a terminal
argument (which lands in shell history) and never through a chat, an issue or a
screenshot:

```bash
make secret k=RADAR_ANTHROPIC_API_KEY
```

If the database password is ever exposed — an error dump prints connection
parameters in the clear, so it happens — reset it in the provider's console and
then run `python scripts/rotate_db_password.py`, which reads the new one from a
hidden prompt and rewrites both URLs in `.env` without echoing it anywhere.

Set `RADAR_CRAWLER_CONTACT` in `.env` before ingesting: every outbound request
carries it in the User-Agent so source operators can reach a human, and
ingestion refuses to run without it.

## Corrections

Every record will carry a "Report an issue" link that opens a pre-filled issue here. Until the site exists, open an issue using the *Correction* template.

## Licence

Code: [MIT](LICENSE). Published data (technologies, developments, claims, assessments): [CC BY 4.0](DATA-LICENSE.md). Source documents remain under their own licences and are linked, not republished.
