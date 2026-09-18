"""Developments: the events that move a technology, and what they link to."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.core.models.base import Base, TimestampMixin, uuid_pk
from radar.core.types import EMBEDDING_DIMENSIONS, DateBasis, DevelopmentKind, EntityStatus

if TYPE_CHECKING:
    from radar.core.models.organization import Organization
    from radar.core.models.technology import Technology


class Development(Base, TimestampMixin):
    """One event: a paper, a demonstration, a pilot, an approval, a funding round.

    A development is the thing several documents can describe — a result
    announced in a preprint, a press release and three news articles is one
    development with four documents behind it, not four developments.

    ``summary`` is generated text and lives here rather than with the claims on
    purpose: claims carry quotes and are evidence, summaries are interpretation.
    Keeping them in different tables is what stops the interface rendering them
    as if they were the same kind of statement (docs/04 rule G.3.8).
    """

    __tablename__ = "development"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('paper', 'demonstration', 'pilot', 'product', 'regulatory', "
            "'funding', 'other')",
            name="kind_valid",
        ),
        CheckConstraint(
            "status IN ('proposed', 'active', 'merged', 'retired')", name="status_valid"
        ),
        # See the note on claim.date_has_basis: a NULL CHECK result passes.
        CheckConstraint(
            "occurred_on IS NULL OR (occurred_basis IS NOT NULL AND "
            "occurred_basis IN ('document_metadata', 'quoted_text'))",
            name="occurred_has_basis",
        ),
        Index("ix_development_occurred_on", "occurred_on"),
        Index("ix_development_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_development_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[DevelopmentKind] = mapped_column(Text, nullable=False)

    occurred_on: Mapped[date | None] = mapped_column()
    occurred_basis: Mapped[DateBasis | None] = mapped_column(Text)

    summary: Mapped[str | None] = mapped_column(
        Text, comment="Generated interpretation. Labelled as such wherever it is shown."
    )
    summary_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_run.id", ondelete="SET NULL")
    )
    summary_stale: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    status: Mapped[EntityStatus] = mapped_column(Text, nullable=False, server_default="proposed")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', title || ' ' || coalesce(summary, ''))", persisted=True),
        nullable=False,
    )

    technologies: Mapped[list[Technology]] = relationship(
        secondary="development_technology", viewonly=True
    )

    def __repr__(self) -> str:
        return f"<Development {self.slug} {self.kind}>"


class DevelopmentTechnology(Base):
    """Which technologies a development is evidence about."""

    __tablename__ = "development_technology"

    development_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("development.id", ondelete="CASCADE"), primary_key=True
    )
    technology_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technology.id", ondelete="CASCADE"), primary_key=True
    )


class DevelopmentOrganization(Base):
    """Who did what in a development.

    ``role`` is part of the primary key because one organisation can hold two
    roles in the same event — a national lab that both funds and evaluates —
    and collapsing that to one row would lose the distinction that decides
    whether the evidence is developer-controlled.
    """

    __tablename__ = "development_organization"
    __table_args__ = (
        CheckConstraint(
            "role IN ('developer', 'partner', 'funder', 'evaluator', 'regulator')",
            name="role_valid",
        ),
    )

    development_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("development.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, primary_key=True)

    organization: Mapped[Organization] = relationship()
