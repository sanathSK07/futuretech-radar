# 02 — Research Methodology and Data-Source Strategy

**Status:** Phase 1 · **Last updated:** 2026-09-17 · **Owner:** SK

Covers sections D (research methodology) and E (data-source strategy).

---

## D. Research methodology

### D.1 Units of analysis

The single most important design decision in this project is that the **claim** is the atomic unit, not the article and not the technology.

| Unit | Definition | Example |
| --- | --- | --- |
| **Source** | A publisher or feed we ingest from, with a reliability tier | arXiv cs.RO; MIT News RSS; Commonwealth Fusion Systems blog |
| **Source document** | One fetched artefact with a URL, publication date, retrieval date, content hash | A preprint; a press release; a conference paper page |
| **Claim** | One atomic assertion extracted from a document, with the verbatim supporting quote, a claim type, and the date the claim refers to | "The SPARC magnet reached 20 T at 20 K" (measured result, 2021-09) |
| **Development** | A cluster of claims describing one identifiable event or result (a paper, a demo, a pilot, an approval) | "Google Willow chip demonstrates below-threshold error correction" |
| **Technology** | A named capability or approach, scoped narrowly enough that a maturity stage is meaningful | "Surface-code error correction on superconducting qubits", not "quantum computing" |
| **Domain** | A grouping of technologies for navigation only; no maturity is assigned to a domain | "Quantum computing" |
| **Organisation** | A university, lab, company, agency or consortium, keyed by ROR ID where one exists | ETH Zürich (ROR 05a28rw58) |
| **Relationship** | A typed, evidenced edge between two technologies or between an organisation and a technology | "HTS tape supply" *bottlenecks* "compact tokamak fusion" |

Consequences: maturity attaches to a Technology (aggregated) and to a Development (individual); a Domain page shows a *distribution* of stages, never a single stage; every stage, rating and summary must point to claim IDs.

### D.2 Source tiers

Source tier describes the *publisher's* reliability and incentives. It does not by itself describe whether a claim is true.

| Tier | Definition | Examples | Handling |
| --- | --- | --- | --- |
| **T1 — Primary, independently reviewed or verifiable** | Peer-reviewed papers; preprints with data or code; patents (as evidence of filing, not of function); regulatory decisions (FDA, NRC, FAA, Health Canada); government lab technical reports; standards bodies | Nature, Science, IEEE Xplore, arXiv with code, FDA 510(k) database, NRC dockets | Eligible as sole support for a stage classification |
| **T2 — Primary, self-interested** | Company technical blogs, official press releases, product documentation, investor filings, university press offices | OpenAI/DeepMind/Anthropic research posts; NVIDIA technical blog; EurekAlert! releases; SEC 10-K risk factors | Reliable for *what the organisation claims* and for dates; not sufficient alone for stages ≥ M4 unless corroborated |
| **T3 — Reputable secondary** | Specialist and science journalism with editorial standards | Nature News, Science News, IEEE Spectrum, MIT Technology Review, Ars Technica, Reuters, Financial Times | Context, corroboration, discovery of T1/T2 sources; can support "reported expectation" claims |
| **T4 — General media and aggregators** | Mainstream news, trade newsletters, Hacker News, Google News | — | Discovery only; claims must be re-sourced to T1–T3 before use |
| **T5 — Excluded** | Anonymous social posts, SEO content farms, press-release rewrites without attribution, sensational YouTube | — | Never ingested |

Tier is stored per Source and can be overridden per Document by a reviewer (e.g., a T3 outlet publishing a primary interview with data).

### D.3 Claim types

Every claim carries exactly one type. This is what allows the UI to separate fact from expectation.

| Type | Meaning | Example phrasing |
| --- | --- | --- |
| `measured_result` | A quantitative or binary result with a stated method | "achieved 99.9% two-qubit gate fidelity on 5 qubits" |
| `demonstration` | Something was shown to work, possibly without full metrics | "robot autonomously folded laundry in a live demo" |
| `deployment` | Real-world use with named users/customers/sites | "installed at 3 customer sites in Texas" |
| `regulatory_event` | Approval, permit, trial-phase entry, standard adoption | "received FDA De Novo clearance" |
| `funding_or_investment` | Money committed (kept for context; not evidence of function) | "raised $400M Series C" |
| `self_reported_claim` | Assertion by the developer without independent verification | "our system outperforms all competitors" |
| `expectation` | Source-reported forecast with an owner ("X expects…") | "the company expects first power by 2027" |
| `expert_forecast` | Forecast by a named third party | "IEA projects…" |
| `opinion` | Interpretation or judgement | "this could transform logistics" |

### D.4 Evidence strength ladder

Evidence strength describes how well a *claim* is supported, combining source tier and claim type. Used in maturity confidence.

1. Independent replication or third-party measurement (T1, `measured_result`, by a different organisation)
2. Peer-reviewed measured result with data/code available (T1)
3. Preprint measured result with code/data (T1)
4. Preprint or report without artefacts (T1, weaker)
5. Third-party-observed demonstration (T3 reporter present, or T1 conference demo)
6. Regulatory event (T1; strong for *deployment readiness*, silent on performance)
7. Developer-controlled demonstration or self-reported result (T2)
8. Developer statement without demonstration (T2, `self_reported_claim`)
9. Expectation or forecast (any tier) — never evidence of current maturity

### D.5 Time labelling

Every dated statement in the system carries one of five epistemic labels. The UI renders them differently and they are never mixed in a sentence.

| Label | Definition | Who asserts it |
| --- | --- | --- |
| **Observed fact** | Happened, with a T1/T2 source and date | Source |
| **Source-reported expectation** | A forecast attributed to a named party in the source | Source |
| **Expert forecast** | A forecast by a credible third party | Source |
| **Model inference** | Produced by our AI pipeline from evidence; shown with model ID and prompt version | Pipeline |
| **Our scenario analysis** | Written by the curator as a conditional scenario ("if X and Y, then Z is plausible by…") | Curator |

### D.6 The research workflow

```
Discover → Fetch → Normalise → Deduplicate → Extract claims (AI) → Link entities →
Propose stage & relationships (AI) → Human review → Publish → Monitor → Periodic re-assessment
```

| Step | Automated? | Notes |
| --- | --- | --- |
| Discover (poll sources) | Yes | Source registry drives schedules and rate limits |
| Fetch & normalise | Yes | Store metadata, abstract, our own summary; respect licences (see E.6) |
| Deduplicate | Yes, with review on borderline | Exact hash → DOI/arXiv ID match → title similarity → embedding similarity with LLM confirmation |
| Extract claims | Yes | Every claim must include a verbatim quote that is programmatically verified to exist in the source text |
| Link entities | Yes, with review for new entities | Organisations resolved to ROR; papers to DOI/arXiv/OpenAlex IDs; new technologies proposed but not created without review |
| Propose maturity stage | Yes | AI must cite claim IDs that satisfy each stage criterion; output is a *proposal* |
| Propose relationships | Yes | Candidate edges with the supporting claim |
| Human review | No | Required before a technology is "featured" or a stage ≥ M4 is published; all other records show an "AI-proposed, unreviewed" badge |
| Publish | Yes | Versioned; every publish creates an assessment version |
| Monitor | Yes | New documents linked to existing developments trigger conflict and staleness checks |
| Re-assess | Semi | Quarterly review of featured technologies; automatic stale flag after N days without new evidence (N configurable per stage) |

### D.7 Signals of meaningful progress (and anti-signals)

Positive signals, in rough order of strength:

1. Independent replication of a key result by a different organisation.
2. Transition of the same capability from paper → prototype → pilot with named partner → generally available product.
3. Regulatory milestones: trial-phase entry, permits, approvals, standards adoption.
4. Quantitative scale or cost metrics moving in the right direction over multiple dated data points (e.g., $/kWh, error rate per gate at fixed qubit count, cycles to 80% capacity).
5. Supply-chain formation: multiple suppliers of a critical input, or a dedicated manufacturing line.
6. Cross-organisation research momentum: growth in T1 publications and in the number of distinct institutions publishing (from OpenAlex), with the caveat in D.8.
7. Deployment evidence with customers who are not also investors.

Anti-signals:

- The same "N years away" horizon repeated across multiple years of sources.
- Demos without metrics, or metrics without method.
- Capability claims only ever in T2 sources.
- Renaming or rebranding of an unchanged programme.
- Funding announcements as the only recent developments.

### D.8 What we refuse to infer

- Causality from counts. Rising publication counts indicate attention, not progress; they are shown as "research activity" with the count and the query that produced it.
- Maturity from money. Funding is stored as context and never counts toward a stage.
- Importance from coverage. Media volume is not an input to any rating.
- Anything from a single T2 source for stages ≥ M4.

---

## E. Data-source strategy

### E.1 Selection principles

Free or free-tier first; official API or feed over scraping; stable identifiers over names; licence-clean storage; one source per document type in the MVP, more later. Every source lives in a version-controlled registry (`sources.yaml`) with its tier, schedule, rate limit, licence note and parser.

### E.2 Verified sources — MVP

Facts below were checked against the cited pages on 2026-09-17.

| Source | What it gives | Access & limits (verified) | Licence / storage note | Role in MVP |
| --- | --- | --- | --- | --- |
| **arXiv** (API, OAI-PMH, RSS) | Preprints across cs.*, quant-ph, cond-mat, physics, eess, q-bio; metadata + abstract; categories | Free. Terms of use: "no more than one request every three seconds, and limit requests to a single connection at a time"; bulk via OAI-PMH, RSS, S3 ([arXiv API ToU](https://info.arxiv.org/help/api/tou.html)) | Metadata (titles, abstracts, authors, IDs) is CC0. Do **not** store or serve e-print PDFs/source unless the individual licence permits; link to arXiv instead | Core paper feed for AI/ML, robotics, quantum, semiconductors, energy physics, some bio |
| **bioRxiv / medRxiv API** | Preprint metadata by date range, category, DOI; preprint→published links | Free; `details`, `pubs`, `publisher` endpoints; 30 records per page ([api.biorxiv.org](https://api.biorxiv.org/)); no rate limit documented — we self-limit to 1 req/s | Metadata only; link to preprint | Core feed for biotech / synthetic biology |
| **OpenAlex API** | 480M works, authors, institutions (ROR-linked), topics, citation counts, funders; abstracts for many journal articles | API key now mandatory (announced 2026-02-24). Free account: **$1/day budget** = unlimited single-ID lookups, 10,000 list/filter calls/day, 1,000 search calls/day. Pay-as-you-go beyond ($0.0001/list call, $0.001/search call). Full dataset snapshot remains free ([OpenAlex blog](https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/); [pricing](https://help.openalex.org/access/pricing/)) | Data is CC0 | **Two roles:** (a) enrichment (citations, institutions, topics) and research-activity counts; (b) **discovery of journal papers in domains where arXiv is thin** — semiconductors (IEEE venues), batteries and energy materials (Joule, Nature Energy, JES), applied biotech — via daily list/filter calls on curated topic IDs and venues. The free budget covers both at MVP volume |
| **Semantic Scholar Graph API** | 214M papers, 2.49B citations, TLDRs, SPECTER2 embeddings, influential-citation counts | Free; with API key, introductory limit 1 request/second; unauthenticated pool is shared and throttled ([S2 API](https://www.semanticscholar.org/product/api)) | Subject to S2 API License Agreement; storing TLDRs unconfirmed | **Deferred to Phase 4** (self-review 2026-09-17): marginal over OpenAlex for the MVP and licence for stored TLDRs unconfirmed |
| **ROR (Research Organization Registry) API** | Canonical organisation records and affiliation-string matching | Free, no registration; max 2,000 requests per 5 minutes per IP ([ROR REST API](https://ror.readme.io/docs/rest-api)) | Open data | Entity resolution for organisations — required in MVP |
| **Official RSS/Atom feeds (curated list, ~40)** | Announcements from universities, labs, companies, agencies | Free; poll daily; respect `robots.txt` and feed TTLs | Store title, link, date, excerpt and our summary; do not republish full article text | Core T2 announcement feed. Initial list in `sources.yaml` (MIT News, Stanford News, Berkeley News, Caltech, ETH, U of T; DeepMind, Google Research, OpenAI, Anthropic, Microsoft Research, NVIDIA Technical Blog, IBM Research; NASA, DOE, NIST, NIH, ESA, CERN, ITER; EurekAlert! topic feeds) |
| **Hugging Face Papers** | Daily/trending ML papers (successor to Papers with Code, which shut down in 2025 and redirects to HF) | Free | Link only | Discovery signal for AI/ML; optional |

### E.3 Verified sources — Phase 4 candidates

| Source | Value | Access (verified) | Why not MVP |
| --- | --- | --- | --- |
| **PatentsView / PatentSearch API (USPTO)** | Granted and pre-grant US patents, assignees, CPC/IPC classes | API key required ("Without an API key your queries will be rejected"); throttled at 45 requests/minute; 27 endpoints ([rOpenSci API changes](https://docs.ropensci.org/patentsview/articles/api-changes.html)) | Patents are a weak, lagging maturity signal; assignee resolution is hard; adds a parser and a review burden before the core loop is proven |
| **Regulatory databases** — openFDA (device/drug approvals), ClinicalTrials.gov API, NRC ADAMS, FAA, Health Canada | The strongest objective evidence for M5–M6 in health, nuclear, aviation | Free public APIs; formats vary | High value; add per domain after MVP once the claim schema is stable |
| **Funding databases** — NSF Award Search, NIH RePORTER, CORDIS (EU), UKRI Gateway to Research, NSERC awards | Research momentum and institution activity | Free APIs/exports | Context, not maturity evidence; defer |
| **SEC EDGAR full-text search** | Public-company risk factors, S-1 technology descriptions | Free | Good for barriers and commercialization claims; defer |
| **OpenReview API** (NeurIPS/ICML/ICLR) | Peer-review status and decisions for ML papers | Free | Useful T1 upgrade signal for arXiv preprints; defer |
| **GDELT** | Global news events | Free, very large | T4 discovery only; noise |
| **Crunchbase, PitchBook, CB Insights, Lens.org commercial API** | Funding and company data | Paid | Out of budget; funding is not maturity evidence anyway |

### E.4 Automated vs human-collected information

| Information | Collect automatically? | Notes |
| --- | --- | --- |
| Paper/preprint metadata, abstracts, categories, citation counts | Yes | arXiv, bioRxiv, OpenAlex, S2 |
| Institution identity and affiliation | Yes (ROR matching) | Human review of low-confidence matches |
| Announcement text from official feeds | Yes | T2; claims extracted but flagged self-reported |
| Claims with quotes, claim types, dates | AI-extracted, programmatically verified | Reviewer spot-checks a sample; all claims behind featured stages are reviewed |
| Candidate maturity stage with evidence pointers | AI-proposed | Human-confirmed for featured technologies and for any stage ≥ M4 |
| Importance ratings | Human, with AI-drafted rationale | Never auto-published |
| Barriers (safety, regulatory, ethical, economic) | AI-extracted from T1–T3 text; human-curated | Often absent from primary sources; curator adds with citations |
| Relationships between technologies | AI-proposed | Human-confirmed before appearing on pages |
| Realistic timeframe | Never inferred automatically | Only source-reported, expert forecast, or curator scenario, each labelled |
| Source tier for a *new* source | Human | Added to `sources.yaml` via pull request |

### E.4a Coverage caveat by domain (added in self-review)

arXiv coverage is strong for AI/ML, robotics and quantum, moderate for fusion/plasma physics, and **weak for semiconductors, batteries and applied biotech**, where the primary literature sits in IEEE venues and paywalled journals. For those domains the MVP relies on OpenAlex metadata and abstracts (CC0) for discovery, plus T2 official feeds (company technical blogs, DOE/NIST/NIH). Expect claim extraction there to work from abstracts and announcements rather than full text, and expect T2 to dominate — which the tier rules already cap at M3 without corroboration. This is a known limitation to state on the methodology page, not something to hide.

### E.5 Volume estimate and filtering

arXiv alone is ~32k submissions/month across all categories (June 2026). The six MVP domains map to roughly a dozen arXiv categories; even at ~20% of volume that is ~200 candidate preprints per day, far more than can be analysed on a $20/month budget or reviewed by one person. The funnel is therefore:

1. **Category and keyword pre-filter** (free): only tracked categories and a per-domain keyword list from `sources.yaml`.
2. **Embedding similarity to tracked technologies** (free, local model): keep documents whose nearest tracked-technology similarity exceeds a threshold, or that match a "watch" query for new-technology discovery.
3. **Cheap LLM triage** (Haiku-class): relevance + domain + "is this a *development* (new result/event) or background?"; target ~100 docs/day.
4. **Full extraction** (Sonnet-class or Haiku via Batch API): ~20–40 docs/day.
5. **Human review**: ~10–20 items/day, ~20–30 minutes.

Numbers are design targets, to be calibrated in Phase 3.

### E.6 Licensing and storage rules

- Store for every document: URL, canonical ID (DOI/arXiv/OpenAlex), title, authors, publication date, retrieval date, abstract or feed excerpt, content hash, source tier, licence field.
- Store full text **only** as a transient processing input where the licence allows fetching (arXiv e-prints for extraction, feed content for extraction); persist extracted claims and verbatim quotes limited to short excerpts, plus our own generated summary. Do not re-serve full articles.
- Honour `robots.txt`, feed TTLs and published rate limits; identify the crawler with a descriptive User-Agent and contact email.
- Attribute every source on every page. Publish our own data as CC-BY 4.0 and code as MIT.
- Canada's fair-dealing provisions are narrower than US fair use; the design above does not rely on either — it relies on metadata licences (CC0), short quotation, and linking.

### E.7 Source registry format (v0)

```yaml
# sources.yaml — one entry per source; changes via pull request
- id: arxiv-cs-ro
  name: arXiv cs.RO (Robotics)
  kind: arxiv_category
  tier: T1
  params: { category: cs.RO }
  schedule: daily
  rate_limit: { requests_per_second: 0.33, concurrency: 1 }
  licence: "metadata CC0; e-prints per-paper licence; link only"
  domains: [robotics]
  parser: arxiv
- id: mit-news-research
  name: MIT News — Research
  kind: rss
  tier: T2
  params: { url: https://news.mit.edu/rss/research }
  schedule: daily
  licence: "excerpt + link; no full-text republication"
  domains: [ai, robotics, energy, biotech, quantum, semiconductors]
  parser: rss
```

---

## Sources consulted for this document

- arXiv API Terms of Use — https://info.arxiv.org/help/api/tou.html
- arXiv blog, 2026-07-09 — https://blog.arxiv.org/2026/07/09/arxiv-now-hosts-over-3-million-articles/
- bioRxiv API — https://api.biorxiv.org/
- OpenAlex blog, "New Features and Usage-Based Pricing", 2026-02-24 — https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/
- OpenAlex pricing — https://help.openalex.org/access/pricing/
- Semantic Scholar API — https://www.semanticscholar.org/product/api
- ROR REST API — https://ror.readme.io/docs/rest-api
- PatentsView API changes (rOpenSci) — https://docs.ropensci.org/patentsview/articles/api-changes.html
- Papers with Code → Hugging Face redirect — https://github.com/paperswithcode/paperswithcode-data/issues/116
- NASA Technology Readiness Levels — https://www.nasa.gov/directorates/somd/space-communications-navigation-program/technology-readiness-levels/
