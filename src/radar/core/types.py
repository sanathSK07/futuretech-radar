"""Controlled vocabularies shared by the ORM models and the pipeline.

These mirror the definitions in docs/02-research-methodology-and-sources.md.
Each is stored as text with a CHECK constraint rather than a native PostgreSQL
enum, because altering a PG enum requires a migration dance that buys nothing at
this scale.
"""

from __future__ import annotations

from enum import StrEnum


class SourceTier(StrEnum):
    """Publisher reliability tier. Describes incentives, not truth of a claim."""

    T1 = "T1"
    """Primary, independently reviewed or verifiable: papers, patents, regulators."""
    T2 = "T2"
    """Primary but self-interested: company blogs, press releases, product docs."""
    T3 = "T3"
    """Reputable secondary: specialist and science journalism."""
    T4 = "T4"
    """General media and aggregators. Discovery only; claims must be re-sourced."""


class SourceKind(StrEnum):
    """Which fetcher implementation handles a source."""

    ARXIV_CATEGORY = "arxiv_category"
    BIORXIV = "biorxiv"
    RSS = "rss"
    OPENALEX = "openalex"
    ROR = "ror"


class FetchStatus(StrEnum):
    """Outcome of a single source poll."""

    RUNNING = "running"
    OK = "ok"
    ERROR = "error"


class DocumentLifecycle(StrEnum):
    """Where a fetched document sits in the pipeline.

    The progression is fetched -> triaged -> extracted -> linked -> assessed,
    with duplicate and irrelevant as terminal states.
    """

    FETCHED = "fetched"
    DUPLICATE = "duplicate"
    IRRELEVANT = "irrelevant"
    TRIAGED = "triaged"
    EXTRACTED = "extracted"
    LINKED = "linked"
    ASSESSED = "assessed"


EMBEDDING_DIMENSIONS = 384
"""Dimensions of BAAI/bge-small-en-v1.5, the local embedding model (ADR-0002)."""
