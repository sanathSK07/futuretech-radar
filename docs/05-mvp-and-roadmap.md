# 05 — MVP Definition and Development Roadmap

**Status:** Phase 1 · **Last updated:** 2026-09-17 · **Owner:** SK

Covers section H (MVP feature set) and section M (development roadmap). Sized to the constraints agreed on 2026-09-17: **6–10 hours/week**, **≤ $20/month**, **six domains deep**.

---

## H. MVP feature set

### H.1 The MVP in one sentence

A daily pipeline that ingests primary sources for six domains, extracts quote-grounded claims, proposes evidence-based maturity stages for ~30 curated technologies, routes proposals through a human review queue, and publishes technology, organisation and development pages where every stage and summary is traceable to dated, tiered sources.

### H.2 Domains (MVP)

| Domain | arXiv categories (initial) | Other MVP feeds |
| --- | --- | --- |
| AI / ML / agents | cs.AI, cs.LG, cs.CL, cs.MA | DeepMind, OpenAI, Anthropic, Google Research, Microsoft Research, Hugging Face Papers |
| Robotics & humanoids | cs.RO | MIT News, Stanford, Berkeley, ETH; company feeds (added via sources.yaml as evidence warrants) |
| Quantum computing | quant-ph | IBM Research, Google Research, university feeds |
| Semiconductors & advanced computing | cs.AR, cs.ET, physics.app-ph (filtered) | NVIDIA Technical Blog, IBM Research, university feeds |
| Energy: fusion, nuclear, batteries | physics.plasm-ph, cond-mat.mtrl-sci (filtered), eess.SY (filtered) | DOE, NIST, ITER, university feeds |
| Biotech & synthetic biology | bioRxiv: synthetic biology, bioengineering, genomics | NIH, EurekAlert! life-science feed, university feeds |

The remaining domains from the brief (cybersecurity, medicine, space, materials, nanotech, BCI, photonics, telecom, manufacturing, climate, water, agtech) are added by configuration after Phase 3 — each needs only feed entries, keyword lists, and seed technology records.

### H.3 Features — MoSCoW

**Must have**

| # | Feature | Acceptance criterion |
| --- | --- | --- |
| M1 | Source registry (`sources.yaml`) with tier, schedule, licence, parser; loaded into DB on deploy | Adding a feed is a one-line PR |
| M2 | Ingestion: arXiv (API/RSS), bioRxiv API, ~40 RSS feeds; rate-limit compliant; idempotent | Re-running a day produces zero duplicates |
| M3 | Deduplication by identifier, hash, title similarity, embedding + LLM confirmation | Eval: precision ≥ 0.95 |
| M4 | Claim extraction with verified quotes, claim types, dates with basis | Eval: precision ≥ 0.90 |
| M5 | Organisation resolution to ROR; unresolved → review queue | Eval: ≥ 0.90 |
| M6 | Technology records (~30 seeded, curated) with aliases, domain, OpenAlex query | Each has ≥ 3 developments with T1/T2 evidence |
| M7 | Maturity stage proposal with evidence pointers, confidence, rationale; versioned assessments | Schema-validated; human gate for ≥ M4 |
| M8 | Review queue: accept / edit / reject claims, entities, stage proposals, edges; audit log | Every public record shows its review status |
| M9 | Public API (read) + admin API (review) with token auth | OpenAPI docs generated |
| M10 | Web UI: Home dashboard ("what changed"), Technology Explorer (domain × stage), Technology Detail (stage + evidence + developments + organisations + open problems), Organisation page, Development page, Search results | Every stage and summary has a working "Why?" |
| M11 | Search: keyword (Postgres full-text, weighted) over technologies, developments, claims, organisations | Query returns in < 500 ms on MVP data |
| M12 | Filters: domain, stage, confidence, date range, review status | Shareable URL state |
| M13 | Citations: every claim shows quote, source, publication date, retrieval date, tier | No claim without a source |
| M14 | Corrections: "Report an issue" on every record opens a pre-filled GitHub Issue (record ID, URL, field); issues are triaged into review tasks by the curator | No form, no stored emails, no spam handling |
| M15 | Analysis run logging with model, prompt version, cost; `radar cost --last 30d` CLI report | Daily cap enforced |
| M16 | Evaluation harness with labelled set; runs in CI | Metrics in G.5 reported |
| M17 | Tests, lint, type checks, CI; Docker Compose dev setup; README and docs | Fresh clone to running app in < 15 minutes |

**Should have (build if Sprint 4 has slack)**

- Semantic search (pgvector) fused with keyword search; pgvector is already used for dedup, so this is ranking work only.
- Additional filters: source tier, organisation.
- Development timeline per technology (simple vertical list by date with stage markers).
- Relationship edges shown as lists on technology pages (data model exists from day 1).
- Methodology page in the web app rendering `docs/02` and `docs/03` (cheap; high portfolio value).
- CSV/JSON export of technologies and claims (CC-BY).

*Self-review note (2026-09-17): semantic search, tier/organisation filters, a corrections form and a cost dashboard were demoted from Must-have to keep the 80-hour budget honest.*

**Won't have in MVP (Phase 4)**

- Graph visualisation; trend charts; alerts; generated reports; Q&A; personalisation; multi-user accounts; patents; funding data; people entities; non-English sources.

### H.4 Seed content plan

Thirty technologies, five per domain, chosen for evidence diversity (at least one M1–M2, one M3–M4, one M5+ per domain) so the maturity model is exercised end-to-end. Seeding is a curated task: for each technology, SK (with AI assistance) identifies 3–6 primary documents, runs the pipeline, and reviews the output. This doubles as the first labelled evaluation set. Expected effort: ~15–20 hours across Sprints 2–3; it is the single most valuable non-coding task in the project.

---

## M. Development roadmap

### M.1 Phases

| Phase | Window | Exit criterion |
| --- | --- | --- |
| **1 — Research & specification** | Sep 2026 (this document set) | Decisions in `08-risks-and-open-questions.md` resolved |
| **2 — MVP** | 2026-09-22 → 2026-11-27 (5 two-week sprints, ~8 h/week ≈ 80 h) | All Must-have criteria met on seed data; deployed demo |
| **3 — Validation** | 2026-11-30 → 2026-12-11 (before exams), plus fixes in January | Eval metrics measured and published; security checklist passed; 3 usability sessions done; fixes shipped |
| **4 — Advanced capabilities** | Jan → Apr 2027, one capability per month | Each capability behind its own ADR |

### M.2 Sprint plan (Phase 2)

| Sprint | Dates | Goal | Deliverables |
| --- | --- | --- | --- |
| **0 — Foundations** | Sep 22 – Oct 4 | Running skeleton with real ingestion | Monorepo; Docker Compose (Postgres 16 + pgvector); Alembic migrations for schema v0; `sources.yaml` loader; arXiv + RSS fetchers with rate limiting; identifier/hash dedup; `fetch_run` logging; CI (ruff, mypy, pytest) |
| **1 — Extraction** | Oct 5 – Oct 18 | Grounded claims from real documents | Triage + extraction prompts and Pydantic schemas; quote verification; ROR resolution; `analysis_run` logging with cost; 20-document labelled set; eval script |
| **2 — Assessment & review** | Oct 19 – Nov 1 | Proposed stages a human can confirm | Technology/Development/Claim linking; embedding + LLM dedup; stage proposal with evidence pointers; assessment versioning; admin review API; minimal review UI (table + accept/edit/reject); seed 15 technologies |
| **3 — Product surface** | Nov 2 – Nov 15 | Public site with traceability | Public read API; Next.js app: dashboard, explorer, technology detail with "Why?", organisation, development, search (FTS + vector); seed remaining 15 technologies |
| **4 — Harden & ship** | Nov 16 – Nov 27 | Deployed, documented MVP | Filters + URL state; corrections; "what changed" feed; deploy (Vercel + API host + Neon); scheduled ingestion via GitHub Actions; README, ARCHITECTURE, methodology docs; demo walkthrough; Should-haves if time |

Each sprint ends with a 30-minute self-review against the section-16 questions, recorded in `PROJECT-STATUS.md`.

### M.3 Phase 3 validation checklist

- Correctness: eval metrics (G.5) on the 50-document set; 10 random public claims manually re-verified against sources.
- Data quality: duplicate rate on a full week's ingestion; stale-record count; conflicting-claim detection on ≥ 5 seeded conflicts.
- Usability: three 20-minute sessions (one P1 peer, one P2/P4-type contact, one non-technical reader) with the task "find out how real X is and show me why".
- Performance: p95 latency for search and technology page on seed data; ingestion job duration and cost per day over 7 days.
- Security: checklist in `07-security-privacy.md`; `pip-audit`, `npm audit`, dependency review; SSRF test cases; admin token rotation drill; ZAP baseline scan on the deployed site.
- AI reliability: grounding failure rate; stage agreement; a prompt-injection test corpus (10 crafted documents) with zero instruction-following.

### M.4 Phase 4 sequencing (proposed, one per month)

1. **Jan 2027 — Relationship graph** (visualisation of confirmed edges; data already exists).
2. **Feb 2027 — Trends** (research-activity series from OpenAlex; stage-change history; "repeatedly appears but does not progress" query).
3. **Mar 2027 — Alerts and digests** (rule-based: stage change, new M4+ evidence, new conflict; weekly email digest).
4. **Apr 2027 — Q&A over claims with citations**, and regulatory/patent sources for two domains.

### M.5 Time budget reality check

80 hours is tight for 17 Must-haves. The mitigations are already in the plan: no auth system (single admin token), no graph UI, no trend charts, no semantic search ranking, a minimal review UI (a table, not a workflow product), corrections via GitHub Issues, and seed content limited to 30 technologies. If Sprint 1 or 2 slips by more than a week, the cut list is, in order: all Should-haves; M10 organisation page (keep as a filtered list of developments); seed set reduced to 18 technologies (three per domain); M12 reduced to domain + stage.
