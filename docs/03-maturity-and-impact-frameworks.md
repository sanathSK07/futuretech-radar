# 03 — Technology Maturity Framework and Importance Framework

**Status:** Phase 1 · **Last updated:** 2026-09-17 · **Owner:** SK

Covers section F (maturity framework) and section 6 of the brief (importance / impact framework).

---

## F. Technology maturity framework

### F.1 Design principles

1. **Stages attach to capabilities, not fields.** A Technology record is scoped so that one stage is meaningful ("solid-state lithium-metal cells for EVs", not "batteries"). Domain pages show the distribution of stages across their technologies.
2. **Every stage has entry criteria expressed as evidence types.** A stage is assigned only when all required evidence exists and is linked by claim ID.
3. **Stage and confidence are separate.** Confidence describes how strong the evidence is, not how far along the technology is.
4. **Higher stages need independent evidence.** Developer-controlled evidence (T2) caps at M3 unless corroborated.
5. **A stage is never inferred from money, headlines, or forecasts.**
6. **Stage changes are versioned** with the evidence and the assessor (human or model) recorded.

The scale is informed by NASA's nine Technology Readiness Levels (TRL 1 "scientific research is beginning" through TRL 9 "flight proven"; [NASA](https://www.nasa.gov/directorates/somd/space-communications-navigation-program/technology-readiness-levels/)) but is deliberately more commercial in its upper stages, since most tracked technologies are not spaceflight systems and TRL 7–9 do not distinguish pilot, early market, and scaled market.

### F.2 The stages

| Stage | Name | Definition | Required evidence (all must be present, linked by claim ID) | Disqualifiers / common false positives | Approx. TRL |
| --- | --- | --- | --- | --- | --- |
| **M0** | Speculative / concept | A proposal, roadmap or theoretical framing with no experimental result for the specific capability | ≥1 T1–T3 document describing the concept | Roadmap slides, "vision" posts, and forecasts are M0 no matter how confident | 1 |
| **M1** | Fundamental research | Experimental or theoretical results on the underlying phenomenon or component; no integrated demonstration of the capability | ≥1 T1 `measured_result` on a component or mechanism | A striking component result (e.g., a new material property) does not make the *system* M2 | 2 |
| **M2** | Proof of concept | The core function demonstrated in a lab under controlled conditions, at least once, with reported metrics and method | ≥1 T1 `measured_result` or T1-reported `demonstration` of the core function with method described | A video demo with no metrics or method is M2 at most and only if third-party observed; otherwise M1 | 3 |
| **M3** | Prototype | An integrated system performs the intended function in a lab or simulated environment; result reproduced (same group, multiple runs) or artefacts (code/data) available | ≥1 T1 `demonstration`/`measured_result` on an integrated system **and** (reproduction claim or artefacts available) | Single-run integrated demo without artefacts stays M2 | 4–5 |
| **M4** | Demonstrated prototype (relevant environment) | Prototype demonstrated outside the developer's controlled setting: independent replication, third-party measurement, field test, or benchmark by a neutral party | ≥1 T1 claim from a *different* organisation than the developer, **or** T3 first-hand observation with metrics, **plus** the M3 evidence | T2-only evidence cannot reach M4; "customer testimonial" in a press release is T2 | 6 |
| **M5** | Pilot / real-world testing | Operating with real users, customers or sites in limited scope; named pilot partners; or formal trial phase (clinical Phase I–III, regulatory test permits, sandbox) | ≥1 `deployment` or `regulatory_event` claim from T1 or from ≥2 independent T2/T3 sources naming the partner/site | A "partnership announcement" without a deployed unit is M4 at most; an LOI or MOU is not a pilot | 7 |
| **M6** | Early commercialisation | Generally available product or service; paying customers not also investors; required regulatory approval obtained; typically low volume, high cost, few vendors | ≥1 `regulatory_event` (where regulation applies) **and** ≥1 `deployment` claim of general availability with paying customers, from T1 or ≥2 independent T2/T3 | "Available for pre-order", waitlists, and unit-of-one bespoke deployments are M5 | 8 |
| **M7** | Scaled commercialisation | Multiple independent vendors or large volumes; declining cost data over time; standards or supply chain established | ≥2 independent vendors with `deployment` evidence **or** T1/T3 volume or cost-curve data across ≥2 dated points | A single dominant vendor at low volume is M6 even with heavy press | 9 |
| **M8** | Mature | Commodity; improvement is incremental; widely deployed across industries | Curator-assigned with citation to an authoritative overview | Rarely tracked; exists so that "established technology" has a home | 9 |

### F.3 Confidence levels

| Confidence | Criteria |
| --- | --- |
| **High** | Required evidence met with ≥2 independent sources, at least one T1, none conflicting, most recent evidence within the staleness window |
| **Medium** | Required evidence met with one T1 source, or ≥2 T2/T3 sources; or minor unresolved conflict |
| **Low** | Required evidence met only by T2, or by a single source, or evidence older than the staleness window, or an unresolved material conflict |
| **Insufficient evidence** | Required evidence not met; the record shows "stage not assessable" rather than a guess |

Staleness windows (default, configurable per domain): M0–M2: 36 months; M3–M4: 24 months; M5: 18 months; M6+: 36 months. A stale record keeps its stage but drops to Low confidence and is flagged for re-assessment.

### F.4 Assignment procedure

1. The pipeline collects all claims linked to the Technology (directly or via its Developments).
2. For each stage from M8 downward, it checks whether the required evidence set is satisfied by claims with adequate source tier and independence. The **highest stage fully satisfied** is proposed.
3. The proposal lists, per criterion, the claim IDs that satisfy it. A proposal without a complete evidence list is rejected by schema validation.
4. Confidence is computed from the satisfying claims (independence, tier, recency, conflicts).
5. A `maturity_assessment` row is written with `status = proposed`, `assessor = model:<id>`, `prompt_version`, `evidence_claim_ids`, `rationale`.
6. Publication rules: stages M0–M3 can be shown as "AI-proposed, unreviewed" with a visible badge; stages ≥ M4 and any *featured* technology require `status = confirmed` by a human reviewer, who may edit the stage, confidence, or evidence set. Every edit creates a new version; the previous version stays queryable.

### F.5 Worked examples (illustrative — to be re-verified with sources during Phase 2 seeding)

- **Sodium-ion batteries for stationary storage.** Multiple vendors have shipped cells and grid-storage installations exist; cost data points exist across years. Expected classification: M6–M7 depending on the independent-vendor and cost-curve evidence actually collected. The MIT Technology Review 2026 list names sodium-ion batteries as a "cheaper, safer alternative to lithium" — that is a T3 opinion claim and is *not* evidence for the stage; the deployments are.
- **Fault-tolerant quantum computation at useful scale.** Below-threshold error correction has been demonstrated on small logical-qubit counts (T1). No useful-scale fault-tolerant computation has been demonstrated. Expected: M2–M3 for "logical qubits with below-threshold error rates"; M0–M1 for "useful-scale fault-tolerant computation". Two separate Technology records.
- **Base-edited personalised gene therapy.** A single-patient bespoke treatment reported in 2025 is a `deployment` at n=1 under regulatory authorisation: M5 (pilot / trial). "Bespoke gene-editing drugs could be approved within the next few years" (MIT TR 2026) is a source-reported expectation, stored as such and excluded from stage logic.

### F.6 What the stage does not mean

- It is not a prediction of success. Many M3 technologies never reach M5.
- It is not a ranking of importance. An M1 technology can be more important than an M7 one.
- It is not comparable across domains in terms of *time*: M4→M6 can take two years in software and fifteen in nuclear.
- It is not a judgement about the organisation's competence.

---

## Importance / impact framework (brief section 6)

### I.1 Principle: ordinal ratings with written rationale, no composite score in the MVP

A single 0–100 "impact score" would be false precision: the inputs are heterogeneous, mostly qualitative, and unevenly evidenced. The MVP uses **six ordinal dimensions**, each rated Low / Medium / High (or Unassessed) with a required rationale and linked claim IDs. There is no weighted total. If a composite is ever added (Phase 4), it must be defined with the measured quantity, calculation, inputs, what it does not mean, and an uncertainty representation — per the brief.

### I.2 Dimensions

| Dimension | Question | Evidence that moves it | What it does *not* mean |
| --- | --- | --- | --- |
| **Technical significance** | Does this change what is physically or computationally possible, or is it incremental? | T1 results vs prior state of the art; expert commentary (T3) | Not novelty of *marketing* |
| **Potential scale of impact (conditional)** | *If it works as claimed*, how many people, industries or systems change? | Addressable applications; industry analyses (T3); curator judgement | Not probability of working; conditional on success |
| **Commercialisation evidence** | Is there objective evidence of paying use, regulatory progress, supply chain? | `deployment`, `regulatory_event` claims; vendor count | Not funding announcements |
| **Research momentum** | Is T1 activity by distinct institutions growing? | OpenAlex counts of works and institutions over the last 3 years, shown with the query | Not causality; attention ≠ progress |
| **Dependency risk** | How much does progress depend on breakthroughs or supply in *other* technologies? | Relationship edges of type `depends_on` / `bottlenecked_by` with evidence | Not a barrier count |
| **Barrier severity** | How serious are the technical, economic, regulatory, safety and ethical barriers? | Extracted barrier claims; regulatory status; cost data | Not a forecast of resolution |

Each rating stores: value, rationale (≤ 120 words), evidence claim IDs, assessor, date, version. Ratings by the model are drafts; publication requires human confirmation.

### I.3 Evidence strength and confidence on ratings

Every rating shows an evidence-strength indicator derived from D.4 (the strongest supporting claim's rung) and the same High/Medium/Low/Insufficient confidence vocabulary as maturity. "Unassessed" is a legitimate, visible state; blank is not.

### I.4 Research-activity metric (the one quantitative signal in the MVP)

Definition: for a Technology with a curated OpenAlex query (topic IDs and/or search terms stored on the record), the count of T1 works per calendar year for the last 5 years, and the count of distinct ROR institutions among their authors' affiliations.

- What is measured: matching works in OpenAlex, by publication year.
- How: stored query executed monthly; results cached with the query string and date.
- What supports it: the query is visible on the page; users can re-run it on OpenAlex.
- What it does not mean: it does not indicate quality, progress, or causality; it is sensitive to the query and to OpenAlex's topic classification.
- Uncertainty: shown with the query's precision note from the curator ("broad query, includes adjacent work").

---

## Sources consulted for this document

- NASA, Technology Readiness Levels — https://www.nasa.gov/directorates/somd/space-communications-navigation-program/technology-readiness-levels/
- MIT Technology Review, 10 Breakthrough Technologies 2026 — https://www.technologyreview.com/2026/01/12/1130697/10-breakthrough-technologies-2026/
- Thoughtworks Technology Radar, ring definitions — https://www.thoughtworks.com/en-us/radar
- Epoch AI, inclusion criteria — https://epoch.ai/data/ai-models-documentation/inclusion
