# ADR-0004: The claim is the atomic unit of evidence

**Status:** Accepted · **Date:** 2026-09-17

## Context

The brief requires that every maturity stage, rating and AI conclusion be traceable to sources, that facts be separated from interpretation, that conflicts and staleness be detectable, and that nothing be invented. Article-level provenance (a link per development) cannot support any of those: a single article contains facts, self-reported claims and forecasts side by side.

## Decision

Extraction produces `claim` rows: one assertion, one verbatim quote (programmatically verified to exist in the source), one claim type, one date with its basis, one epistemic label. Developments group claims; technologies aggregate developments; assessments cite claim IDs per criterion. Claims are immutable once confirmed (edits retract and replace).

## Alternatives considered

- **Document-level provenance:** simpler; rejected because it cannot distinguish "measured 20 T" from "expects first plasma in 2027" within the same document.
- **Free-text rationale with citations only:** rejected because it cannot be validated in code or queried for conflicts.

## Consequences

More rows and a more demanding extraction prompt; in exchange, quote verification removes most hallucination, conflicts become a query, staleness is per-claim date, and the "Why?" UI is a join rather than a reconstruction. Extraction cost is bounded by the triage funnel.
