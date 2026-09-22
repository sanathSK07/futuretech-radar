# ADR-0007: Harvest arXiv over OAI-PMH, not the Atom search API

**Status:** Accepted · **Date:** 2026-09-22

## Context

Eleven of the sixteen registry entries are arXiv categories, and for a week they
failed unpredictably: some categories returned `200` while their neighbours,
fetched seconds apart with identical headers, returned `406`. Five explanations
were written down before one survived contact with evidence — transient load
shedding, a per-category property, load shedding again, request headers, HTTP
protocol version. Each was stated after one or two samples and each was wrong.

The sixth came from reading the response headers rather than theorising about
them. A `200` carries `age: 178` and `x-cache: MISS, HIT, HIT`; the `406`
alongside it carries `x-cache: MISS, MISS` and `cache-control: private,
no-store`. `export.arxiv.org/api/query` sits behind an edge cache that serves
what it has stored and refuses anything that would require an origin fetch.

Confirmed by varying one parameter at a time, ten samples per cell rather than
one: `start=100` refused 0/8 while `start=0` returned 8/8; `max_results=99`
refused 0/8 while `max_results=100` returned 8/8. Nothing about the *content* of
the request matters. Only whether that exact URL is already warm.

This is fatal for the search API as a harvest transport, because a daily job
asks a question nobody asked yesterday by definition. It also means the URL is a
cache key, which is why a cosmetic change to the query string — unescaping the
colon in `cat:` — broke categories that had worked all week: it asked for eleven
cold URLs at once.

## Decision

Harvest arXiv metadata over `https://export.arxiv.org/oai2`, arXiv's documented
OAI-PMH interface, as a new source kind `arxiv_oai`.

- One source per category, unchanged, but `params.set` carries a setSpec as
  `ListSets` reports it (`cs:cs:RO`, `physics:quant-ph`, `q-bio:q-bio:BM`)
  rather than a dotted category name. All eleven categories have a set; verified
  against a live `ListSets` returning 183 sets on 2026-09-21.
- Paging follows `<resumptionToken>` until it is absent or empty, with a repeat
  guard and a page ceiling that is logged when reached.
- Source ids are unchanged, so documents already stored stay attached to their
  source and re-ingestion still inserts nothing new.
- The Atom fetcher stays in the codebase, but no registry entry points at it any more, so `make smoke-arxiv` smokes the OAI transport. It is a safety net while the new transport is unproven in production, not a supported path, and is deleted once the OAI harvest has run clean against the live API for a week.

## Alternatives considered

- **Keep the search API and retry harder.** Rejected. Retrying only helps when
  another client happens to warm the URL, which is not a mechanism this project
  can depend on and is precisely what disguised the problem as load shedding.
- **Keep the search API and never change the query string.** Rejected. It
  freezes today's URLs, so the window can never move — which is the one thing a
  daily harvest must do.
- **Scrape the listing pages.** Rejected: fragile, and against arXiv's terms
  when a documented bulk interface exists.
- **Use a third-party mirror or an aggregator.** Rejected: adds a T2 hop in
  front of a T1 primary source, which is backwards for this project.

## Consequences

- OAI's `from` filters on a record's *datestamp*, set on creation **or**
  revision. The harvest window is therefore a superset of "submitted in this
  window". Kept deliberately: a revised paper is a discovery, and because
  `external_id` is the versionless arXiv id under `ON CONFLICT DO NOTHING`, a
  revision of a stored paper writes nothing and a revision of an unseen one is
  stored once.
- The arXiv metadata format carries no version number, so `arxiv_version` is not
  recorded on this path; `<updated>` is kept instead, which says a revision
  happened without claiming which one. This does not change the existing debt
  that a revision never updates stored metadata.
- Responses are much larger — a single `ListRecords` page for the whole `cs` set
  measured 4,076,389 bytes — so `DEFAULT_MAX_BYTES` rose from 5 MB to 32 MB.
- `406` stays in `TRANSIENT_STATUSES`, with its docstring corrected. It is not
  load shedding, and the retry is not principled; it is kept because the Atom
  fetcher still exists for smoke tests and a retry sometimes catches a URL a
  passing client warmed.
- One more migration (`0003`) to widen the `source.kind` CHECK.

## What this cost, and the process change

Five wrong diagnoses, each stated as a finding after one or two samples, and one
of them shipped as a code change that broke working sources. The failure was not
ignorance of caches — it was treating a 2×2 experiment with a single sample per
cell as a result. The rule taken from it: **a claim about a flaky system needs a
sample size, and a claim about a server needs its response headers read**, not
inferred from status codes. That is the same standard this project applies to
its own published claims, applied to its own engineering.
