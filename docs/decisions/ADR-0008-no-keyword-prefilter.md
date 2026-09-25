# ADR-0008: No keyword prefilter before triage; a title-first model pass instead

**Status:** Accepted · **Date:** 2026-09-25

## Context

The first OAI-PMH harvest stored 2,751 documents in one day, 2,738 of them from
arXiv. Sending every one through a model daily is the largest cost line in the
project, and the brief caps spend at $20/month. A deterministic gate was built to
decide which documents are worth asking a model about: a document passed if it
mentioned a tracked-domain term **and** carried a claim signal (demonstration,
deployment, regulatory event, record, or a measured quantity).

It was measured against the real corpus before anything depended on it, with
`radar prefilter report`, which writes nothing. The measurement is why this ADR
exists.

## What the measurement showed

**Pass rate 55.4%** — 1,525 of 2,751. As a cost gate that is close to worthless:
it removes under half the spend while adding a component to maintain.

Worse, both error directions were wrong in ways that matter.

**It passed theory papers.** `benchmark` was in the AI term list. It is also the
most common word in method papers, so a condensed-matter paper titled "Exact
benchmarks for the plasmon-pole approximation" matched domain `ai`. Verified by
re-running the gate on that exact title: `terms=('benchmark',)`.

**The claim-signal half did not work at all.** `demonstrat` fired on 971 of the
1,525 passes. In engineering and press register "demonstrated" means a working
thing was shown; in academic register "we demonstrate that X" means "we prove".
The term cannot tell those apart, and nor can any keyword. This is the
conceptual error at the centre of the design: the signal the gate needed to read
is register, and register is not a vocabulary.

**It rejected the highest-value documents.** Re-running the gate on four rejected
titles returned `terms=()` — not one domain term — for:

- "Energy Department Announces Speed to Power Investments Across 26 States"
- "Introducing Gemini 3.8 Live with Live Avatar"
- "New cell-collection device could improve early cancer detection"
- "Spin-Polarized Magnetic Metal Electrodes for Magnetic Tunnel Junctions"

A government funding announcement, a product launch, a medical device, and a
materials result. The vocabulary was written from arXiv's register and is blind
to newsroom register — which is exactly why those sources were added, since
arXiv structurally cannot carry deployment, regulatory or commercialisation
evidence.

**And the gate should never have applied to them.** 13 of 2,751 documents came
from the non-arXiv sources. Half a percent. Gating thirteen documents a day to
save money is not a trade-off, it is a mistake with no upside. (Thirteen
documents is not a rate and nothing here is claimed from it; the finding is the
mechanism above, established by inspection.)

## Decision

No keyword prefilter. Triage is a model pass, in two stages:

1. **Title only, minimal output.** A title is roughly 30 input tokens against
   roughly 350 for title-plus-abstract, and a first-pass verdict needs one
   token, not a JSON object. The model reads register, which is the thing
   keywords cannot.
2. **Full abstract for survivors**, returning the existing `TriageDecision`.

Non-arXiv sources skip stage 1 entirely and go straight to stage 2. At thirteen
documents a day the saving from gating them is a rounding error and the cost of
missing one is a whole evidence class.

## What it costs

Haiku 4.5 at $1/MTok input and $5/MTok output, halved by the Batch API, so
$0.50 and $2.50 (platform.claude.com/docs/en/about-claude/pricing, read
2026-09-25). Per month, at 2,738 arXiv documents a day:

| Approach | Input | Output | Total |
| --- | --- | --- | --- |
| Full abstract, `TriageDecision` output, every document | $14.60 | $16.60 | **$31.20** |
| Title only, single-token output | $1.25 | $0.60 | **$1.85** |
| Full abstract for survivors, assuming 20% survive | $2.90 | $3.30 | **$6.20** |
| Title-first, both stages | | | **≈ $8.05** |

Two things to note. Output dominates the naive approach — the decision object is
longer than the title it judges — which is why stage 1 returns one token. And
the 20% survival rate is an **assumption, not a measurement**; the first live
stage-1 run replaces it, and if it comes back at 60% this ADR needs revisiting
rather than quietly absorbing the cost.

## Alternatives considered

- **Tune the vocabulary.** Drop `benchmark`, `demonstrat`, `record`, `inference`,
  `agent`, `node`, `yield`; add newsroom and materials vocabulary. Rejected: it
  raises the ceiling of an approach whose ceiling is low, and every fix risks a
  false negative that nothing in the system will ever report.
- **Keep the gate for arXiv only, skip it for newsrooms.** Rejected on the same
  grounds — it fixes the 0.5% problem and leaves the register problem, which is
  the one that passed 971 theory papers.
- **Narrow the arXiv categories.** Still available and orthogonal; cs.AI and
  cs.LG are 1,341 of 2,738. Deferred until stage 1 gives a measured survival
  rate, because dropping a category is irreversible in a way that adjusting a
  prompt is not.
- **Haiku 3.5 at $0.80/$4.** Rejected: 20% cheaper for a judgement that depends
  entirely on following an instruction about register precisely.

## Consequences

- No schema change was made for the gate, so nothing has to be unwound.
- `prefilter.py`, `prefilter.yaml` and `radar prefilter report` stay until
  2026-10-02 so the numbers above can be reproduced, then are deleted with the
  Atom fetcher. Kept past that date they are rot, not evidence.
- The measurement approach is the part worth keeping: build the cheap thing,
  point it at a real day's corpus, read the samples, and be willing to throw it
  away. A 55.4% pass rate looked like a partial success in the summary line and
  was a failure in the samples underneath it.
