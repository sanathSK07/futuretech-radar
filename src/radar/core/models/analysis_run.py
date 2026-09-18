"""Every model call this system makes, recorded so an output can be explained."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from radar.core.models.base import Base, uuid_pk
from radar.core.types import AnalysisStage, AnalysisStatus


class AnalysisRun(Base):
    """One call to a model, with everything needed to reproduce and price it.

    Every AI-produced row in the database points at one of these. That is what
    makes "why does it say this?" answerable: the model ID, the prompt version
    (a git SHA, so the exact text is recoverable), the documents that went in,
    and the raw output before validation.

    ``ungrounded_claims`` counts claims dropped because their quote could not be
    found in the source. It is deliberately a first-class column rather than a
    key inside ``raw_output``: it is the primary health metric of the extraction
    stage, and a number that has to be dug out of JSON is a number nobody plots.
    """

    __tablename__ = "analysis_run"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('triage', 'extract', 'dedupe', 'assess', 'relate', 'summarise')",
            name="stage_valid",
        ),
        CheckConstraint(
            "status IN ('ok', 'schema_error', 'refusal', 'error')", name="status_valid"
        ),
        CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="cost_not_negative"),
        Index("ix_analysis_run_stage_created_at", "stage", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    stage: Mapped[AnalysisStage] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Git SHA of the prompt file used for this call."
    )
    input_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="The model's response before validation, kept for debugging."
    )

    tokens_in: Mapped[int | None] = mapped_column()
    tokens_out: Mapped[int | None] = mapped_column()
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    duration_ms: Mapped[int | None] = mapped_column()

    records_written: Mapped[int] = mapped_column(nullable=False, server_default="0")
    ungrounded_claims: Mapped[int] = mapped_column(
        nullable=False,
        server_default="0",
        comment="Claims discarded because the quote was not found in the source.",
    )

    status: Mapped[AnalysisStatus] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<AnalysisRun {self.stage} {self.model_id} {self.status}>"
