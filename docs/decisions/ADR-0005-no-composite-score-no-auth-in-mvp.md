# ADR-0005: No composite importance score and no user auth in the MVP

**Status:** Accepted · **Date:** 2026-09-17

## Context

Dashboards with a single "impact score" look impressive and are usually meaningless: inputs are heterogeneous, mostly qualitative and unevenly evidenced. The brief explicitly forbids fake precision. Separately, the MVP has one curator and anonymous readers; a user system adds weeks of work and a large attack surface with no user to serve.

## Decision

Importance is six ordinal dimensions (Low/Medium/High/Unassessed) with required rationale and evidence claim IDs, no weighted total. Public reads are anonymous; the review surface is protected by a single server-side admin token exchanged for a signed session cookie via a one-field login page. Multi-user auth (Auth.js/Clerk) and any composite score are Phase 4 items that each require their own ADR defining measurement, calculation, inputs, non-meaning and uncertainty.

## Alternatives considered

- **Weighted composite score:** rejected for false precision; if reintroduced it must be defined per brief section 6.
- **FastAPI-Users / Auth.js from day one:** rejected; premature.

## Consequences

The dashboard ranks by *evidence events* (stage changes, new M4+ evidence, conflicts) rather than by a score, which is more honest and more useful. A future multi-user system must migrate `review_action.actor_id` from a fixed string to a user ID; the column is already free text to make that trivial.
