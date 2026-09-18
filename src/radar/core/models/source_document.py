"""A fetched artefact: the evidence every claim is later traced back to."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.core.models.base import Base, TimestampMixin, uuid_pk
from radar.core.types import EMBEDDING_DIMENSIONS, DocumentLifecycle, SourceTier

if TYPE_CHECKING:
    from radar.core.models.fetch_run import FetchRun
    from radar.core.models.source import Source


class SourceDocument(Base, TimestampMixin):
    """One fetched document, stored metadata-first.

    Two deliberate departures from the schema sketch in
    docs/06-architecture-stack-data.md, both found while implementing:

    1. ``external_id`` is NOT NULL. PostgreSQL treats NULLs as distinct in a
       unique constraint, so a nullable external_id would let a re-run insert
       duplicate rows for the same document. Fetchers fall back to the canonical
       URL when a feed supplies no identifier, which makes re-running a day's
       ingestion genuinely idempotent.

    2. ``content_hash`` is indexed but NOT unique. The sketch had it unique,
       which contradicts ``duplicate_of``: identical content legitimately arrives
       from two sources (a syndicated press release), and we want to *record*
       that relationship, not reject the second row with an integrity error.
    """

    __tablename__ = "source_document"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_id", name="uq_source_document_source_id_external_id"
        ),
        CheckConstraint(
            "lifecycle IN ('fetched', 'duplicate', 'irrelevant', 'triaged', "
            "'extracted', 'linked', 'assessed')",
            name="lifecycle_valid",
        ),
        CheckConstraint(
            "tier_override IS NULL OR tier_override IN ('T1', 'T2', 'T3', 'T4')",
            name="tier_override_valid",
        ),
        CheckConstraint(
            "duplicate_of IS NULL OR duplicate_of <> id",
            name="duplicate_not_self",
        ),
        CheckConstraint(
            "lifecycle <> 'duplicate' OR duplicate_of IS NOT NULL",
            name="duplicate_has_target",
        ),
        Index("ix_source_document_content_hash", "content_hash"),
        Index("ix_source_document_published_at", "published_at"),
        Index("ix_source_document_lifecycle", "lifecycle"),
        Index(
            "ix_source_document_search_tsv",
            "search_tsv",
            postgresql_using="gin",
        ),
        Index(
            "ix_source_document_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    external_id: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Feed-supplied identifier, or the URL when none is given."
    )
    canonical_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Stable identifiers: {doi, arxiv, openalex, pmid}.",
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    abstract: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(
        Text,
        comment=(
            "Transient extraction input. Cleared after extraction where the "
            "source licence does not permit storage (docs/02 section E.6)."
        ),
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    licence: Mapped[str | None] = mapped_column(Text)
    tier_override: Mapped[SourceTier | None] = mapped_column(Text)

    lifecycle: Mapped[DocumentLifecycle] = mapped_column(
        Text, nullable=False, server_default="fetched"
    )
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_document.id", ondelete="SET NULL")
    )
    fetch_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fetch_run.id", ondelete="SET NULL")
    )

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, ''))",
            persisted=True,
        ),
        nullable=False,
    )

    source: Mapped[Source] = relationship(back_populates="documents")
    fetch_run: Mapped[FetchRun | None] = relationship()
    duplicate_target: Mapped[SourceDocument | None] = relationship(remote_side="SourceDocument.id")

    @property
    def effective_tier(self) -> SourceTier:
        """The tier that governs this document: a reviewer override, else the source's."""
        return self.tier_override or self.source.tier

    def __repr__(self) -> str:
        return f"<SourceDocument {self.source_id}:{self.external_id} {self.lifecycle}>"
