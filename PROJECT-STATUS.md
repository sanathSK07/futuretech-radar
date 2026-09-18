# PROJECT-STATUS — FutureTech Radar

Living tracker. Update at the end of every working session. Newest entries first within each list.

**Phase:** 1 complete → Phase 2 (MVP) starts 2026-09-22
**Last updated:** 2026-09-17

## Current task

- Sprint 0 · Task 2: Docker Compose (Postgres 16 + pgvector), `packages/core` with settings and SQLAlchemy models for `source`, `fetch_run`, `source_document`, first Alembic migration, CI (ruff, mypy, pytest). (~4 h)
- Then Task 3: `sources.yaml` + `radar ingest --since 1d` for arXiv with the 3-second limiter and a zero-duplicates re-run test. (~4 h) Target: real documents in the database from a scheduled GitHub Actions run by 2026-09-29.

## Completed

- 2026-09-17 — Sprint 0 · Task 1: repository skeleton and initial commit — root README written around the evidence model, MIT `LICENSE`, `DATA-LICENSE.md` (CC BY 4.0), `.gitignore`, `SECURITY.md`, Dependabot config (Actions, pip, npm), Correction issue template. Push to `github.com/sanathSK07/futuretech-radar` and repository security settings: see notes below.
- 2026-09-17 — Phase 1 research and specification: `docs/01`–`08`, ADR-0001–0006, executive summary. Verified sources for APIs, pricing, hosting limits, competitors.

## Repository notes (Task 1 hand-off, 2026-09-17)

- Local repo: `~/Documents/futuretech-radar` on the Mac, branch `main`, one commit (`9b48203`), author Sanath Kumar Kamaraj. A byte-identical copy exists in the Cowork session workspace.
- **Push (SK, one command, from a terminal in that folder):** `gh repo create sanathSK07/futuretech-radar --public --source=. --remote=origin --push` — or create an empty public repo on github.com and run `git remote add origin https://github.com/sanathSK07/futuretech-radar.git && git push -u origin main`.
- **Security settings after the push** (Settings → Advanced Security): secret scanning and push protection are on by default for new public personal repos (GitHub changelog, 2024-03-11) — verify they show *Enabled*; enable **Dependabot alerts** and **Dependabot security updates**; enable **Private vulnerability reporting** (referenced by `SECURITY.md`). Version updates come from `.github/dependabot.yml` automatically.
- Task 1 is complete when the repo is public with those four toggles on.

## Blocked

- None. (Q1–Q8 in `docs/08-risks-and-open-questions.md` have defaults; unanswered questions do not block Sprint 0.)

## Unresolved questions

- Q1 public/private repo · Q2 name/domain · Q3 Anthropic-only · Q4 curator time commitment · Q5 demo date · Q6 seed list authorship · Q7 admin UI location · Q8 English-only. Defaults listed in `docs/08`.

## Technical debt (known at design time, accepted)

- Single admin token instead of user auth (ADR-0005). Replace in Phase 4.
- Review UI is a table, not a workflow product.
- No trend, alert, report or graph features; schema supports them.
- Staleness computed at read time; fine at MVP scale, may need materialisation later.
- Semantic search is dedup-only in the MVP; ranking fusion is a Should-have.
- Semantic Scholar enrichment deferred to Phase 4 (licence for stored TLDRs unconfirmed).
- Corrections via GitHub Issues rather than an in-app workflow.

## Known bugs

- None yet (no code).

## Research gaps

- Primary sources for the 30 seed technologies (to be collected during Sprints 2–3; worked examples in `docs/03` are illustrative until sourced).
- bioRxiv API rate-limit policy undocumented.
- Regulatory data sources (openFDA, NRC, FAA, Health Canada) unverified; Phase 4.
- OpenReview API terms; Phase 4.

## Future improvements (Phase 4 backlog, each needs an ADR)

- Relationship graph visualisation (Jan 2027)
- Trend analysis from OpenAlex research-activity series and stage history (Feb 2027)
- Rule-based alerts and weekly digest (Mar 2027)
- Q&A over claims with citations; regulatory and patent sources for two domains (Apr 2027)
- Multi-user auth; personalisation; non-English sources; people entities via ORCID

## Decisions log

See `docs/decisions/`. ADR-0001 stack · ADR-0002 Postgres-only · ADR-0003 GitHub Actions scheduling · ADR-0004 claim as atomic unit · ADR-0005 no composite score / no auth in MVP · ADR-0006 human review gate.

## Sprint self-review log

- (Sprint 0 review due 2026-10-04.) Questions to answer each time: What assumptions did I make? What could be wrong? What evidence is missing? What features are unnecessary? What could fail at scale? What security vulnerabilities exist? Where could AI hallucinate? Where could data become stale? What would a senior engineer criticise? What would make this stronger as a portfolio project?
