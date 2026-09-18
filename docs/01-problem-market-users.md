# 01 — Problem, Market and Users

**Status:** Phase 1 (research & specification) · **Last updated:** 2026-09-17 · **Owner:** SK

This document covers sections A (problem and opportunity), B (existing solutions / competitor analysis) and C (personas and use cases) of the Phase 1 brief.

---

## A. Problem and opportunity

### A.1 The problem in one sentence

People who need to know *how real* an emerging technology is cannot get that answer from any existing tool without doing the evidence work themselves, every time.

### A.2 Why this is hard

**Volume.** arXiv alone received 32,040 new submissions in June 2026 and now hosts over 3 million articles ([arXiv blog, 2026-07-09](https://blog.arxiv.org/2026/07/09/arxiv-now-hosts-over-3-million-articles/)). That is one preprint server. Add bioRxiv, conference proceedings, patents, company technical blogs, press releases, regulatory filings and government lab announcements, and no individual can read the primary literature across even six domains.

**Signal contamination.** The most-shared descriptions of a technology are usually the least evidential: press releases, funding announcements, and headlines that use "breakthrough" for a lab result with n=1. A demo video, a peer-reviewed measurement, and a shipped product all get reported with the same verb ("unveils").

**Maturity is per-application, not per-field.** "Quantum computing" is simultaneously a commercially sold product (annealers and cloud-accessible gate-model machines), a pilot-stage capability (error-corrected logical qubits at small scale), and fundamental research (fault-tolerant computation at useful scale). A single stage label for a field is meaningless; the label has to attach to a specific capability or development. Most tools assign one label per field anyway.

**Provenance is discarded.** Aggregators keep a link; analyst reports keep a footnote; neither keeps the *specific claim*, its date, its source type, and who reported it. Without that, staleness is invisible and conflicting claims cannot be surfaced.

### A.3 Who has this problem

The problem is felt by anyone who has to make a decision that depends on technology timing: a student choosing a research direction or a specialisation, an engineering lead deciding whether to build on a platform, a policy analyst writing a briefing, a journalist checking a claim, a small investor or founder assessing a space. Each of them currently does ad-hoc research, gets an answer coloured by whichever sources they happened to find, and cannot reuse the work.

### A.4 The opportunity, stated honestly

As a *commercial* product, this space is crowded at the top (Gartner, CB Insights, ITONICS, Lux, IDTechEx) and cheap at the bottom (newsletters, Perplexity, free academic search). A solo student project will not out-compete either on breadth or on distribution. That is fine, because that is not the goal.

As a *portfolio and research* product, the opportunity is real and specific: no open, continuously updated tool exposes an evidence-graded maturity model with inspectable provenance across multiple deep-tech domains. Building one demonstrates exactly the skills the brief lists: data engineering (ingestion, dedup, provenance), AI engineering (grounded extraction, evaluation, traceability), system design, security, and research methodology. The methodology itself is a defensible artefact even if the software never scales.

Secondary opportunity: the methodology and dataset can be published openly (CC-BY data, MIT code), which is what makes the project citable and what makes reviewers trust it. Epoch AI's credibility comes from published inclusion criteria and downloadable data, not from a UI.

### A.5 What "success" means for Phase 2

The MVP is successful if a sceptical reader can open any technology page, see a maturity stage, click through to the specific dated claims and sources that justify it, and either agree or file a correction. If that loop works for ~30 technologies across 6 domains, the product thesis is validated. Everything else (graphs, alerts, trends) is Phase 4.

---

## B. Existing solutions and competitor analysis

### B.1 Landscape by category

| Category | Representative products | Strengths | Weaknesses for this problem | Price / access |
| --- | --- | --- | --- | --- |
| **Analyst radar platforms** | Gartner Hype Cycle for Emerging Technologies; CB Insights (Mosaic score, market maps); ITONICS Radar; Futures Platform; Lux Research; IDTechEx | Breadth (Gartner reports screening ~2,000 technologies per year); expert judgement; polished radar visuals; enterprise workflow (rating, collaboration) | Scoring is proprietary and not disclosed at placement level; annual or twice-yearly cadence; evidence behind a placement is not shown; expensive; optimised for corporate strategy not technical truth | Gartner: client-only, full report gated; CB Insights: enterprise subscription; ITONICS: free trial, pricing undisclosed |
| **Academic discovery and AI research assistants** | Semantic Scholar (214M papers, free API); OpenAlex (480M works, CC0 data, usage-priced API); Elicit; Consensus; Undermind; alphaXiv; Connected Papers; Hugging Face Papers (successor to Papers with Code, which shut down in 2025) | Massive coverage; citation graphs; free or cheap; some extraction (Elicit) and evidence synthesis (Consensus) | Paper-centric: no notion of maturity, commercialization, pilots, regulatory status or organisation-level activity; Consensus's own docs say it "struggles with niche, theoretical, or emerging research areas"; Elicit's coverage is weighted to biomedical/social science | Semantic Scholar: free; OpenAlex: free $1/day API budget; Elicit: free tier then $12/mo; Consensus: free tier then $8.99/mo |
| **Editorial lists and radars** | MIT Technology Review "10 Breakthrough Technologies" (2026 list published 2026-01-12); WEF Top 10 Emerging Technologies; Thoughtworks Technology Radar (vol. 34, April 2026; rings Adopt / Trial / Assess / Caution); IEEE Spectrum; Nature News | Curated and readable; Thoughtworks demonstrates that an *ordinal, categorical* maturity signal with written rationale is more honest and more useful than a numeric score | Annual/biannual; not queryable; no structured evidence; selection is editorial debate rather than stated criteria | Free |
| **Rigorous single-domain datasets** | Epoch AI (notable AI models; explicit notability criteria; CC-BY; daily CSV); Stanford AI Index 2026; Our World in Data | Published inclusion criteria; sources on every record; downloadable data; uncertainty stated | AI-only; not designed as a general emerging-technology radar | Free |
| **Government horizon scanning** | Policy Horizons Canada (MetaScan; "Weak Signals"); UK Government Office for Science; OECD; NATO S&T trends; WIPO Technology Trends | Policy framing; explicit weak-signal methodology; public-sector credibility | Periodic PDFs; Policy Horizons' flagship "MetaScan 3: Emerging Technologies" is dated 2014 and its recent output is scenario-based (e.g., "Scenarios for an AI-enabled World", 2026-02-10) rather than a continuously updated evidence base | Free |
| **General AI answer engines** | Perplexity; ChatGPT / Claude deep research; Exa | Fast, broad, conversational | No persistent structured record; no maturity model; hallucination risk; answers are not reproducible or comparable across time | Free / subscription |
| **News aggregators and newsletters** | Google News, Techmeme, Hacker News, domain newsletters | Timeliness | Volume without grading; publicity conflated with importance | Free |

### B.2 What the strong players do that we should copy

1. **Epoch AI**: publish the inclusion criteria (a model is "notable" if it meets any of: >5,000 citations; training cost >$1M 2023-USD or ≥1% of the most expensive model to date; >1M monthly active users; state-of-the-art benchmark performance; equivalent historical significance; staff discretion). Every record carries sources. Data is CC-BY and updated daily. **Copy:** explicit, written inclusion and stage criteria; per-record sources; open data.
2. **Thoughtworks Radar**: four rings with plain-English definitions and a written blip rationale. **Copy:** ordinal categories with rationale text, not a 0–100 score.
3. **Gartner**: a large candidate funnel narrowed by stated impact criteria. **Copy:** the funnel shape (many candidates → few featured), not the opacity.
4. **Semantic Scholar / OpenAlex**: stable identifiers (DOI, OpenAlex IDs, ROR IDs for institutions). **Copy:** canonical IDs for every entity, never free-text org names as keys.

### B.3 Where existing solutions are weak (the gap)

None of the categories above provides all four of: (1) continuous ingestion from primary sources; (2) an evidence-graded maturity stage attached to a specific capability, with the evidence shown; (3) organisation tracking across papers, patents, products and pilots; (4) inspectable AI analysis where extracted facts are separated from generated interpretation. FutureTech Radar targets exactly that intersection, at small scale first.

---

## C. User personas and use cases

Personas are grounded in the categories of people described in A.3. They are hypotheses to validate in Phase 3, not survey results.

### P1 — The direction-chooser (student / early researcher)

*"I have one year to pick a specialisation. Which of these fields is actually moving, and which has been 'five years away' for twenty years?"*

Needs: maturity stage with evidence; research momentum over time; which organisations are active; what the open problems are. Cares about honesty more than polish. **Primary MVP persona.**

Key questions: What is the difference between what has been demonstrated and what is promised? Who are the serious groups? What would I need to learn to work on this?

### P2 — The technology analyst (small consultancy / corporate strategy / VC associate)

*"I need a defensible one-page brief on solid-state batteries by Friday, and my firm does not pay for CB Insights."*

Needs: sourced, dated claims; maturity with confidence; commercialization evidence (pilots, customers, regulatory approvals); export/citation. Will pay for time saved if the sourcing is trustworthy.

### P3 — The policy analyst (public sector)

*"Which technologies should be on our department's watch list, and what regulatory barriers are they hitting?"*

Needs: barriers (safety, regulatory, ethical); dependency chains (e.g., fusion → superconducting magnets → HTS tape supply); neutral, non-promotional language; a stable record to cite in a briefing. Relevant to Canadian public-sector horizon scanning, where the flagship emerging-technologies scan is over a decade old.

### P4 — The engineering lead

*"Should we build on this platform now, trial it, or wait?"*

Needs: a Thoughtworks-style categorical verdict per capability with rationale; competing approaches; what infrastructure or chips it depends on; realistic timeframe with the basis for it.

### P5 — The science journalist / fact-checker

*"A press release says 'first-ever'. Is it?"*

Needs: prior developments in the same technology; conflicting claims flagged; source tiering; the specific quote behind a claim.

### P6 — The curator (internal)

The human reviewer who confirms or rejects AI-proposed classifications, resolves conflicts, and approves featured technologies. In the MVP this is SK. This persona's workflow (the review queue) is a first-class MVP feature, not an admin afterthought, because the product's credibility depends on it.

### C.1 Core use cases (MVP)

| ID | Use case | Persona | MVP? |
| --- | --- | --- | --- |
| UC1 | Browse technologies by domain and maturity stage; open a technology page | P1–P5 | Yes |
| UC2 | On a technology page, read the maturity stage and click through to each supporting claim, quote, source, date and source tier | P1–P5 | Yes |
| UC3 | Search across technologies, developments, organisations and claims (keyword + semantic) | all | Yes |
| UC4 | Filter developments by domain, stage, date range, source tier, organisation, review status | all | Yes |
| UC5 | Open an organisation page: developments, technologies, linked sources | P1, P2, P3 | Yes (basic) |
| UC6 | See "what changed this week": new developments, stage changes, new conflicts, newly reviewed items | all | Yes |
| UC7 | Review queue: accept / edit / reject AI-proposed claims, entities and stage proposals; every action logged | P6 | Yes |
| UC8 | Report a correction on any record | all | Yes (simple) |
| UC9 | View a development timeline for one technology | P1, P4 | Should |
| UC10 | View dependency / relationship edges as a list | P3, P4 | Should |
| UC11 | Relationship graph visualisation | P3, P4 | Phase 4 |
| UC12 | Trend analysis (momentum over time) | P1, P2 | Phase 4 |
| UC13 | Alerts on meaningful developments | P2, P3 | Phase 4 |
| UC14 | Generated research brief on a technology or question | P2, P3 | Phase 4 |
| UC15 | Natural-language Q&A over the internal database with citations | all | Phase 4 |

### C.2 Non-goals

- Investment recommendations or financial advice.
- Real-time news; a daily batch cadence is sufficient and cheaper.
- Tracking individual researchers as entities in the MVP (privacy surface, entity-resolution difficulty, low value relative to organisations). Revisit in Phase 4 with ORCID-based resolution.
- Multi-tenant SaaS features (teams, billing, personalization) in the MVP.

---

## Sources consulted for this document

- arXiv blog, "arXiv now hosts over 3 million articles", 2026-07-09 — https://blog.arxiv.org/2026/07/09/arxiv-now-hosts-over-3-million-articles/
- Gartner, "Hype Cycle for Emerging Technologies" (public article) — https://www.gartner.com/en/articles/hype-cycle-for-emerging-technologies
- MIT Technology Review, "10 Breakthrough Technologies 2026", 2026-01-12 — https://www.technologyreview.com/2026/01/12/1130697/10-breakthrough-technologies-2026/
- Thoughtworks, Technology Radar vol. 34, April 2026 — https://www.thoughtworks.com/en-us/radar
- Epoch AI, AI Models documentation (inclusion criteria; CC-BY) — https://epoch.ai/data/ai-models-documentation/inclusion
- Stanford HAI, 2026 AI Index Report — https://hai.stanford.edu/ai-index/2026-ai-index-report
- Semantic Scholar API product page — https://www.semanticscholar.org/product/api
- OpenAlex blog, "New Features and Usage-Based Pricing", 2026-02-24 — https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/
- Elicit / Consensus / Semantic Scholar comparison (secondary; pricing and stated limitations) — https://thedrive.ai/blog/elicit-vs-consensus-ai-research-tools
- ITONICS Radar product page — https://www.itonics-innovation.com/radar
- Policy Horizons Canada, Emerging Technologies (MetaScan) — https://horizons.service.canada.ca/en/category/projects/metascan/emerging-technologies/index.shtml
- Papers with Code shutdown (secondary) — https://www.coursera.org/articles/papers-with-code ; redirect confirmed at https://github.com/paperswithcode/paperswithcode-data/issues/116
