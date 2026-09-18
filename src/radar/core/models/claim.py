"""The claim: one assertion, one verbatim quote, one type, one date basis.

This is the atomic unit of the whole system (ADR-0004). Everything downstream —
maturity stages, technology pages, the "Why?" view — is an arrangement of these
rows, and nothing may assert anything a claim does not support.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.core.models.base import Base, TimestampMixin, uuid_pk
from radar.core.types import ClaimStatus, ClaimType, DateBasis, EpistemicLabel

if TYPE_CHECKING:
    from radar.core.models.source_document import SourceDocument


class Claim(Base, TimestampMixin):
    """One assertion extracted from one document, with the quote that supports it.

    Three of the grounding rules in docs/04 section G.3 are enforced here, in
    the database, rather than only in the pipeline that writes it:

    1. **A stored claim is a verified claim.** ``quote_verified`` carries a CHECK
       that it is true. The pipeline drops claims whose quote is not a substring
       of the source and counts them in ``analysis_run.ungrounded_claims``; this
       constraint means no future code path — a migration, a backfill script, a
       careless fixture — can introduce an ungrounded claim by accident. The
       column stays rather than being implied, because an invariant that is
       written down is one a reader can check.

    2. **A date must have a basis.** ``date_referenced`` without ``date_basis``
       is rejected, so no date can enter the system without saying whether it
       came from document metadata or from the quoted text itself.

    3. **A forecast is never an observed fact.** A claim typed ``expectation``
       or ``expert_forecast`` may not carry the ``observed_fact`` label. This is
       the single rule the brief cared most about, and a CHECK constraint is a
       cheaper guarantee than a prompt instruction and a code review.

    Claims are not edited after confirmation. A correction creates a new claim
    and retracts the old one, so a page that cited the original keeps meaning
    what it meant.
    """

    __tablename__ = "claim"
    __table_args__ = (
        CheckConstraint("quote_verified", name="quote_must_be_verified"),
        # "date_basis IN (...)" is NULL when date_basis is NULL, and a CHECK
        # that evaluates to NULL passes. The IS NOT NULL test is what makes this
        # constraint bite; without it a date with no basis sailed straight in.
        CheckConstraint(
            "date_referenced IS NULL OR (date_basis IS NOT NULL AND "
            "date_basis IN ('document_metadata', 'quoted_text'))",
            name="date_has_basis",
        ),
        CheckConstraint(
            "claim_type IN ('measured_result', 'demonstration', 'deployment', "
            "'regulatory_event', 'funding_or_investment', 'self_reported_claim', "
            "'expectation', 'expert_forecast', 'opinion')",
            name="claim_type_valid",
        ),
        CheckConstraint(
            "epistemic_label IN ('observed_fact', 'source_expectation', 'expert_forecast')",
            name="epistemic_label_valid",
        ),
        CheckConstraint(
            "claim_type NOT IN ('expectation', 'expert_forecast') "
            "OR epistemic_label <> 'observed_fact'",
            name="forecast_is_not_observed_fact",
        ),
        CheckConstraint(
            "status IN ('proposed', 'confirmed', 'rejected', 'retracted')", name="status_valid"
        ),
        CheckConstraint("length(quote) > 0", name="quote_not_empty"),
        Index("ix_claim_document_id", "document_id"),
        Index("ix_claim_development_id", "development_id"),
        Index("ix_claim_status_claim_type", "status", "claim_type"),
        Index("ix_claim_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_document.id", ondelete="CASCADE"), nullable=False
    )
    development_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("development.id", ondelete="SET NULL")
    )

    text: Mapped[str] = mapped_column(
        Text, nullable=False, comment="The claim, normalised into one sentence."
    )
    quote: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Verbatim from the source. Verified as a substring."
    )
    quote_verified: Mapped[bool] = mapped_column(nullable=False)

    claim_type: Mapped[ClaimType] = mapped_column(Text, nullable=False)
    epistemic_label: Mapped[EpistemicLabel] = mapped_column(Text, nullable=False)

    date_referenced: Mapped[date | None] = mapped_column()
    date_basis: Mapped[DateBasis | None] = mapped_column(Text)

    metrics: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, comment="[{name, value, unit}]. Every value must appear in the quote."
    )
    subjects: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        comment=(
            "Mentions as the model found them: [{kind, surface, resolved_id}]. "
            "Resolution to an entity is deterministic, never a model decision."
        ),
    )

    status: Mapped[ClaimStatus] = mapped_column(Text, nullable=False, server_default="proposed")
    conflicts_with: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="RESTRICT"), nullable=False
    )
    review_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_action.id", ondelete="SET NULL")
    )

    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
        nullable=False,
    )

    document: Mapped[SourceDocument] = relationship()

    def __repr__(self) -> str:
        return f"<Claim {self.claim_type} {self.status} {self.text[:40]!r}>"
