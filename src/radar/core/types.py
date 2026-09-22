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
    """The Atom search API. Kept for smoke tests; see ARXIV_OAI."""
    ARXIV_OAI = "arxiv_oai"
    """arXiv's OAI-PMH harvest interface, and the way bulk arXiv metadata arrives."""
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


class ClaimType(StrEnum):
    """What kind of assertion a claim is (docs/02 section D.3).

    Exactly one per claim. This is the vocabulary that lets the interface keep
    fact and expectation apart instead of flattening both into "news".
    """

    MEASURED_RESULT = "measured_result"
    """A quantitative or binary result with a stated method."""
    DEMONSTRATION = "demonstration"
    """Something was shown to work, possibly without full metrics."""
    DEPLOYMENT = "deployment"
    """Real-world use with named users, customers or sites."""
    REGULATORY_EVENT = "regulatory_event"
    """Approval, permit, trial-phase entry, standard adoption."""
    FUNDING_OR_INVESTMENT = "funding_or_investment"
    """Money committed. Context only: funding is not evidence that a thing works."""
    SELF_REPORTED_CLAIM = "self_reported_claim"
    """An assertion by the developer without independent verification."""
    EXPECTATION = "expectation"
    """A forecast attributed to a named party in the source."""
    EXPERT_FORECAST = "expert_forecast"
    """A forecast by a credible third party."""
    OPINION = "opinion"
    """Interpretation or judgement."""


class EpistemicLabel(StrEnum):
    """How a dated statement is known (docs/02 section D.5).

    Only the three source-asserted labels appear here. The other two labels in
    D.5 — model inference and curator scenario — describe content this system
    *produces* (summaries, stage proposals, scenarios), never an extracted
    claim. Allowing them on a claim would let generated text be stored in the
    same shape as quoted evidence, which is the one confusion the whole design
    exists to prevent.
    """

    OBSERVED_FACT = "observed_fact"
    SOURCE_EXPECTATION = "source_expectation"
    EXPERT_FORECAST = "expert_forecast"


class DateBasis(StrEnum):
    """Where a claim's date came from. A date with no basis is rejected."""

    DOCUMENT_METADATA = "document_metadata"
    QUOTED_TEXT = "quoted_text"


class ClaimStatus(StrEnum):
    """Review state of a claim. Claims are never edited in place once confirmed."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    RETRACTED = "retracted"


class EntityStatus(StrEnum):
    """Review state of a curated entity: technology, organisation, development."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    MERGED = "merged"
    RETIRED = "retired"


class DevelopmentKind(StrEnum):
    """What sort of event a development is."""

    PAPER = "paper"
    DEMONSTRATION = "demonstration"
    PILOT = "pilot"
    PRODUCT = "product"
    REGULATORY = "regulatory"
    FUNDING = "funding"
    OTHER = "other"


class OrganizationKind(StrEnum):
    """What sort of body an organisation is."""

    UNIVERSITY = "university"
    COMPANY = "company"
    GOVERNMENT = "government"
    LAB = "lab"
    NONPROFIT = "nonprofit"
    CONSORTIUM = "consortium"


class OrganizationRole(StrEnum):
    """How an organisation relates to a development."""

    DEVELOPER = "developer"
    PARTNER = "partner"
    FUNDER = "funder"
    EVALUATOR = "evaluator"
    REGULATOR = "regulator"


class AnalysisStage(StrEnum):
    """Which pipeline stage a model call belongs to."""

    TRIAGE = "triage"
    EXTRACT = "extract"
    DEDUPE = "dedupe"
    ASSESS = "assess"
    RELATE = "relate"
    SUMMARISE = "summarise"


class AnalysisStatus(StrEnum):
    """Outcome of a model call.

    ``schema_error`` and ``refusal`` are separated from ``error`` because they
    mean different things about the prompt: the first says the contract needs
    tightening, the second says the input tripped a safety boundary, the third
    says the network or the provider failed.
    """

    OK = "ok"
    SCHEMA_ERROR = "schema_error"
    REFUSAL = "refusal"
    ERROR = "error"


class ReviewReason(StrEnum):
    """Why something is queued for a human."""

    NEW_ENTITY = "new_entity"
    HIGH_STAGE = "high_stage"
    CONFLICT = "conflict"
    LOW_CONFIDENCE = "low_confidence"
    UNGROUNDED_QUOTE = "ungrounded_quote"
    USER_REPORT = "user_report"


class ReviewTaskStatus(StrEnum):
    """State of a review task."""

    OPEN = "open"
    DONE = "done"
    DISMISSED = "dismissed"


class ReviewActionKind(StrEnum):
    """What a reviewer did."""

    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"
    MERGE = "merge"
    RETRACT = "retract"
