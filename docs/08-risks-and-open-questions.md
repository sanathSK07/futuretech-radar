# 08 — Major Technical Risks, Open Questions and Assumptions

**Status:** Phase 1 · **Last updated:** 2026-09-17 · **Owner:** SK

Covers sections N (major technical risks) and O (questions or assumptions that must be resolved).

---

## N. Major risks

Likelihood and impact are qualitative (L/M/H). Ordered by expected damage to the project.

| # | Risk | L | I | Mitigation | Owner / trigger |
| --- | --- | --- | --- | --- | --- |
| R1 | **Scope creep.** The brief lists ~28 domains, 20 analysis questions per development, graphs, trends, alerts, reports, Q&A, personalisation. Building toward all of it stalls the MVP | H | H | MoSCoW in `05-mvp-and-roadmap.md`; the cut list in M.5; each Phase 4 feature needs an ADR; sprint self-review asks "what did I add that was not on the list?" | SK; any sprint that adds an unlisted feature |
| R2 | **Execution stall.** Long planning phases followed by restarts | H | H | Sprint 0 starts 2026-09-22 with three concrete tasks (see summary doc); a working ingestion by day 7; commit at least twice a week; `PROJECT-STATUS.md` is updated at every session's end | SK; two weeks without commits |
| R3 | **Extraction quality.** Hallucinated or mis-typed claims undermine the whole premise | M | H | Quote verification in code; claim-type rubric with examples; eval set with precision target ≥ 0.90; human gate on featured/≥ M4 | Eval below target |
| R4 | **Maturity subjectivity.** Two reasonable reviewers assign different stages | M | M | Evidence-typed criteria; confidence separate from stage; scope notes per technology; inter-rater check in Phase 3; publish the rubric so disagreement is about evidence, not taste | Phase 3 κ < 0.6 |
| R5 | **Entity resolution.** Organisation names vary; startups are absent from ROR; technology aliases explode | M | M | ROR affiliation matching with threshold; unresolved → review; alias table curated; merge operation supported in schema | Resolution accuracy < 0.9 |
| R6 | **Dedup failures.** Same development reported by preprint, press release and three news outlets creates three developments | M | M | Identifier match → title similarity → embedding + LLM confirm; merge workflow in review; conflicts remain visible | Duplicate rate > 5% in weekly audit |
| R7 | **Free-tier limits.** Neon 0.5 GB; Render spin-down; GitHub Actions delays; OpenAlex $1/day | M | M | Store abstracts not full text; chunk sparingly; cost cap; measure storage weekly; $5–7/month always-on API if demo cold starts hurt | Storage > 350 MB; failed scheduled runs |
| R8 | **Licence / ToS exposure.** Storing or serving content beyond what licences allow | L–M | M | Metadata-first design; `content_text` cleared post-extraction where required; excerpt + link UI; rate-limit compliance; identified crawler | Any takedown request |
| R9 | **Cost creep.** Model upgrades or larger documents raise per-day spend | M | M | Per-run cost accounting; hard daily cap; Batch API; Haiku for high-volume steps; prompt caching for the rubric | Cost > $0.60/day for 3 days |
| R10 | **Staleness.** Records look authoritative long after evidence has moved on | M | M | Staleness windows per stage; confidence downgrade; "last evidence" date on every page; re-assessment tasks | Stale count > 20% of featured |
| R11 | **Prompt injection / poisoned sources.** | L–M | M | No tools; schema-only outputs; allow-listed sources; proposals only; test corpus | Any injection test failure |
| R12 | **Portfolio credibility.** Reviewers dismiss the project as "LLM summaries with a UI" | M | H | Publish methodology, rubric, evaluation numbers and data (CC-BY); make "Why?" the hero interaction; write the README around the evidence model, not the stack | Feedback in Phase 3 sessions |
| R13 | **Over-engineering.** Adopting queues, graph DBs, microservices, or Kubernetes because they look impressive | M | M | ADR-0002/0003; "one database, one scheduled job, two deployables" rule until a measured need exists | Any infra PR without an ADR |
| R14 | **Single-curator bottleneck.** Review queue outgrows 30 min/day | M | M | Funnel targets in E.5; auto-confirm only for M0–M2 claims from T1 with verified quotes (still badged); triage thresholds tuned in Phase 3 | Queue > 50 open items |
| R15 | **Uneven source coverage.** Semiconductors, batteries and applied biotech are under-represented on arXiv; the MVP will lean on T2 feeds and OpenAlex abstracts there, producing more self-reported claims and lower confidence | H | M | OpenAlex as a discovery source for journal papers (E.2); tier caps already prevent T2-only M4+; state the limitation on the methodology page; add IEEE/journal RSS where available | Confidence distribution skews Low in those domains |

## O. Open questions and assumptions

### O.1 Decisions already taken with SK (2026-09-17)

- Deliverable format: repo-ready Markdown docs plus an executive-summary doc.
- Budget: ≤ $20/month for LLM API and hosting.
- Time: 6–10 hours/week.
- MVP scope: six domains deep (AI/ML/agents; robotics & humanoids; quantum; semiconductors & advanced computing; energy — fusion/nuclear/batteries; biotech & synthetic biology).

### O.2 Decisions needed before Sprint 0 (SK to answer)

| # | Question | Default if unanswered | Why it matters |
| --- | --- | --- | --- |
| Q1 | Public or private GitHub repository from day one? | **Public** | Free unlimited Actions minutes; portfolio visibility; forces secret hygiene early. Private costs 2,000 min/month and hides the work |
| Q2 | Project name and slug: keep "FutureTech Radar" / `futuretech-radar`? Domain purchase (~$10–15/yr) now or later? | Keep the name; buy the domain only at deploy (Sprint 4) | Naming is a stall risk; decide once |
| Q3 | Anthropic as the sole LLM provider for the MVP? | **Yes**, behind a thin provider interface so a second provider can be added in Phase 4 | Structured outputs and Batch API are verified; multi-provider abstraction now is over-engineering |
| Q4 | Are you willing to be the curator at ~20–30 min/day, 4–5 days/week, during Phase 2–3? | Assumed **yes**; if not, MVP shows only AI-proposed records with badges and no featured technologies | The human gate is what makes the product credible |
| Q5 | Deployed demo required by a specific date (e.g., for co-op applications)? | Target **2026-11-27** | Fixes Sprint 4's priority if slips occur |
| Q6 | Seed technologies: do you want to propose the 30, or should I draft the list with scope notes for you to edit? | I draft; you edit | ~2 hours of your review time |
| Q7 | Should the review UI be in the Next.js app (shared components, one deploy) or a separate minimal admin app? | **Same app**, `/admin` routes behind the session cookie | Simplicity |
| Q8 | English-only sources for MVP? | **Yes** | Multilingual adds parsers, models and review burden |

### O.3 Assumptions to validate in Phase 2–3

- A1: ~100 triaged documents/day across six domains is enough to surface meaningful developments weekly. (Validate by counting confirmed developments per week.)
- A2: Haiku-class extraction reaches ≥ 0.90 precision with quote verification. (Validate with the eval set; fall back to Sonnet for extraction if not.)
- A3: ROR resolves ≥ 90% of organisation mentions in academic sources; startups will need manual entries. (Measure.)
- A4: Abstract-level embeddings suffice for dedup and relevance; full-text chunking is unnecessary for the MVP. (Measure dedup recall.)
- A5: The staleness windows in F.3 are reasonable defaults. (Review after 8 weeks of data.)
- A6: Free tiers hold for the MVP data volume (< 350 MB in Neon). (Measure weekly.)
- A7: Three usability sessions are enough to catch the major UI failures. (Judgement.)
- A8: GitHub Actions' schedule delays (minutes to hours) are acceptable for a daily batch. (Monitor; if not, move to a Render cron job.)
- A9: Extracting from abstract + selected sections (~5k tokens) captures the claims that matter for maturity assessment; full text is not needed for the MVP. (Validate on the eval set by comparing claim recall against a full-text run on 10 documents.)

### O.4 Research gaps (to close during Phase 2 seeding)

- Verified primary sources for each of the 30 seed technologies (none are cited in this Phase 1 set; the worked examples in `03-...md` are illustrative until sourced).
- Regulatory data sources per domain (openFDA, NRC, FAA, Health Canada) — endpoint verification deferred to Phase 4.
- OpenReview API terms — deferred.
- bioRxiv API rate-limit policy is undocumented; we self-limit and should ask.
- Whether Semantic Scholar's API licence permits storing TLDRs (likely display-with-attribution; confirm before use).
