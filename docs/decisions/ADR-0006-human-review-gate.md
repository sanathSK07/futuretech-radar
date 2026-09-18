# ADR-0006: Human review gate for high-stakes fields; badged AI proposals elsewhere

**Status:** Accepted · **Date:** 2026-09-17

## Context

Requiring human review of everything makes a one-person project impossible to keep current; publishing everything the model proposes makes the product untrustworthy. The brief requires that speculation never be presented as fact and that AI conclusions be inspectable.

## Decision

- **Hard gate (human confirmation required before public display):** any maturity stage ≥ M4; any technology marked *featured*; all importance ratings; all technology relations; creation of new technologies and organisations; any curator scenario text.
- **Badged auto-publish:** claims with verified quotes from T1/T2 sources, stage proposals M0–M3, development summaries — shown with an "AI-proposed, unreviewed" badge, model ID and prompt version, and a one-click "Why?" panel.
- **Never automated:** timeframes; entity creation; deletion.

## Alternatives considered

- **Review everything:** rejected; queue would exceed the curator's ~30 min/day within a week.
- **Publish everything with a global disclaimer:** rejected; violates the brief's anti-hallucination requirement and the product thesis.

## Consequences

The review queue is a first-class product surface with prioritisation (`high_stage`, `conflict`, `new_entity`, `user_report`). Thresholds (which stages auto-publish, which sources qualify) are configuration and will be tuned with Phase 3 evaluation data.
