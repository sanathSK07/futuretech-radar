# 04 — AI Analysis Framework

**Status:** Phase 1 · **Last updated:** 2026-09-17 · **Owner:** SK

Covers section G (AI-analysis framework) and sections 11–12 of the brief (AI system design; data quality and anti-hallucination).

---

## G.1 Where AI is used, and where it is not

| Task | AI? | Model class | Why |
| --- | --- | --- | --- |
| Relevance triage (is this document about a tracked technology / a new development?) | Yes | Small (Haiku 4.5) | High volume, low stakes, cheap |
| Claim extraction with verbatim quotes and claim types | Yes | Mid (Sonnet 5) or Haiku 4.5 via Batch | Core value; needs precision |
| Entity mention extraction (organisations, technologies, dates, metrics) | Yes, then deterministic resolution | Same call as extraction | Resolution to ROR/DOI is code, not LLM |
| Duplicate confirmation for near-duplicate documents/developments | Yes, on candidates only | Small | Embedding similarity shortlists; LLM confirms |
| Maturity stage proposal with evidence pointers | Yes | Mid | Rubric-driven; output is a proposal |
| Relationship (edge) proposal | Yes | Mid | Candidate edges with supporting claim |
| Development and technology summaries | Yes | Mid | Labelled "generated interpretation" |
| Importance ratings | Draft only | Mid | Human confirms; never auto-published |
| Timeframes | **No** | — | Only source-reported, expert, or curator scenarios |
| Creating new organisations, technologies or sources | **No** (proposes only) | — | Anti-hallucination: entity creation is a human action |
| Q&A over the database with citations | Phase 4 | Mid | RAG over claims; not MVP |
| Digest / brief generation | Phase 4 | Mid | After core loop is trusted |

Model choice is a configuration value, not a code dependency; prices used for the cost model are from the Claude pricing page on 2026-09-17: Haiku 4.5 $1 / $5 per MTok (input / output), Sonnet 5 $2 / $10, Batch API 50% off, cache reads 0.1× input ([pricing](https://platform.claude.com/docs/en/about-claude/pricing)).

## G.2 Pipeline stages and contracts

Each stage is a pure function `(inputs, prompt_version, model_id) → structured output`, logged as an `analysis_run` with inputs, raw output, tokens, cost and duration. Outputs are validated against JSON schemas using the API's structured outputs (`output_config.format` with `type: "json_schema"`, supported on Haiku 4.5 and Sonnet 5; schema adherence is guaranteed except on refusal or `max_tokens` — [structured outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). Pydantic models are the single source of truth for the schemas.

```
SourceDocument
   │  (1) triage ──────────────► TriageResult {relevant, domains[], is_development, reason}
   │
   ├─ (2) extract ─────────────► ExtractionResult {claims[], mentions[], suggested_development_title}
   │        each Claim: {text, quote, claim_type, date_referenced, date_basis, metrics[], subjects[]}
   │
   ├─ (3) resolve (code) ──────► resolved orgs (ROR), papers (DOI/arXiv/OpenAlex), technologies (alias table)
   │
   ├─ (4) link/dedupe ─────────► candidate Development match (embedding top-k → LLM confirm)
   │
   ├─ (5) stage proposal ──────► MaturityProposal {stage, confidence, criteria[{criterion, claim_ids[]}], rationale}
   │
   ├─ (6) relation proposal ───► [{source_tech, target_tech, type, claim_ids[], rationale}]
   │
   └─ (7) summarise ───────────► {development_summary, what_demonstrated, what_experimental, limitations[]}
                                  each field carries claim_ids[]
```

## G.3 Grounding rules (enforced in code, not just in prompts)

1. **Quote verification.** Every extracted claim must include a verbatim quote. The pipeline normalises whitespace and checks the quote is a substring of the source text; claims that fail are dropped and counted as `ungrounded_claims` in the run metrics. This single rule removes fabricated facts. It does **not** catch a real quote paired with a misleading paraphrase or a wrong claim type; those are what the labelled evaluation set (G.5, "supported / unsupported / mis-typed") and reviewer spot-checks are for.
2. **No new entities.** Extraction returns *mentions* (surface strings). Resolution to entities is deterministic: organisations via ROR affiliation matching with a score threshold; papers via identifiers; technologies via a curated alias table. Unresolved mentions go to the review queue as "proposed entity" and are not shown publicly.
3. **Dates must have a basis.** `date_referenced` must be accompanied by `date_basis ∈ {document_metadata, quoted_text}`; a date not present in either is rejected.
4. **Numbers must be quoted.** Any numeric metric in a claim must appear in the quote.
5. **Evidence pointers must exist.** Stage proposals, summaries and relation proposals reference claim IDs; a referenced ID that does not exist or does not belong to the technology fails validation and the run is rejected (retry once, then queue for review).
6. **Sufficiency check.** The stage proposal schema includes `insufficient_evidence: bool`; the prompt instructs the model to set it rather than guess, and the rubric criteria are in the prompt verbatim from `03-maturity-and-impact-frameworks.md` (single source, loaded at build time so the docs and the prompt cannot drift).
7. **Untrusted input.** Fetched text is data. The prompt places it inside delimiters, instructs the model that instructions inside documents are content to be reported, and the pipeline has no tools the model can call; the only side effect is a validated JSON object written to `proposed` status.
8. **Separation of extracted vs generated.** Claims (with quotes) and summaries (generated) are different tables, rendered in different UI components with different labels. A summary sentence without a claim ID is rendered but marked "unsupported".

## G.4 Traceability: what a user can inspect

For any AI-produced field the UI offers "Why?", which opens: the model ID; prompt version (git SHA of the prompt file); the input document IDs; the claim IDs cited, each with quote and source; the raw rationale; the review status and reviewer edits, with diffs between versions. This is stored, not reconstructed.

## G.5 Evaluation (Phase 3 gate)

The MVP is not "done" until these are measured on a hand-labelled set.

| Metric | Method | Target (initial) |
| --- | --- | --- |
| Claim extraction precision | 50 documents labelled by SK; each extracted claim judged supported / unsupported / mis-typed | ≥ 0.90 supported |
| Claim recall (important claims) | For the same 50 docs, list of "must-extract" claims; fraction found | ≥ 0.70 |
| Quote-grounding failure rate | Automatic | reported, trend down |
| Claim-type accuracy | Labelled | ≥ 0.85 |
| Maturity proposal agreement | 30 technologies; model proposal vs SK's rubric-based label; exact and ±1 stage | ≥ 0.60 exact, ≥ 0.90 within ±1 |
| Duplicate detection | 40 known pairs + 40 non-pairs | precision ≥ 0.95, recall ≥ 0.80 |
| Org resolution accuracy | 100 mentions | ≥ 0.90 |
| Cost per processed document | Automatic | tracked; budget alarm at $0.60/day |

Inter-rater reliability on maturity (SK vs one other reader on 20 technologies, Cohen's κ) is a Phase 3 nice-to-have that would strengthen the methodology write-up.

## G.6 Cost model (MVP, daily batch)

Assumptions: rubric/system prompt ~3k tokens cached (cache read 0.1×); triage 100 docs × ~1.5k input (title + abstract) + 150 output; extraction 30 docs × ~5k input + 1.5k output; stage/relations/summary 15 developments × ~6k input + 1k output.

**Extraction input is capped at ~5k tokens per document**: abstract plus introduction, results/limitations and conclusion sections selected by heading heuristics, not the full paper. Feeding full arXiv papers (10–20k tokens) would roughly triple extraction cost; it is a Phase 4 option for featured technologies only.

| Step | Model | Tokens/day (in / out) | Cost/day (list) | Cost/day (Batch, −50%) |
| --- | --- | --- | --- | --- |
| Triage | Haiku 4.5 | 150k / 15k | $0.225 | $0.11 |
| Extraction | Haiku 4.5 | 150k / 45k | $0.375 | $0.19 |
| Extraction (alt.) | Sonnet 5 | 150k / 45k | $0.75 | $0.375 |
| Stage + relations + summary | Sonnet 5 | 90k / 15k | $0.33 | $0.165 |
| **Total (Haiku extraction, Batch)** | | | | **≈ $0.47/day ≈ $14/month** |
| **Total (Sonnet extraction, Batch)** | | | | **≈ $0.65/day ≈ $20/month** |

Embeddings run locally (sentence-transformers, e.g. `BAAI/bge-small-en-v1.5`, CPU) in the scheduled job at zero API cost. Hosting on free tiers (see `06-architecture-stack-data.md`). The budget fits the $20/month cap with Haiku extraction and leaves headroom; Sonnet extraction is the stretch. Backfill of the seed set (~300 documents) is a one-time ≈ $3–5 via Batch.

## G.7 Prompt management

Prompts live in `packages/pipeline/prompts/*.md` with YAML front matter (`name`, `version`, `model`, `schema`). The rubric sections are included from the docs at build time. Every `analysis_run` stores the prompt file's git SHA. Changing a prompt requires re-running the evaluation set in CI (`make eval`) and the diff in metrics is posted in the PR.

## G.8 Failure modes and responses

| Failure | Detection | Response |
| --- | --- | --- |
| Hallucinated claim | Quote check | Drop; count |
| Hallucinated organisation | Resolution fails | Review queue as proposed entity |
| Over-confident stage | Rubric validation + human gate for ≥ M4 | Proposal only; badge |
| Prompt injection in fetched text | No tools; schema-only output; content delimiters | Report as content; run flagged if output contains instruction-like text |
| Model drift after upgrade | Eval set in CI | Block deploy if metrics regress beyond tolerance |
| Cost spike | Per-run cost accounting; daily cap | Job aborts at cap; alert |
| Stale summary after new evidence | New claims linked to a development mark summary `stale` | Re-summarise on next run; old version retained |
