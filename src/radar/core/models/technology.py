"""Technologies: the curated capabilities this system tracks over time."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.core.models.base import Base, TimestampMixin, uuid_pk
from radar.core.types import EMBEDDING_DIMENSIONS, EntityStatus

if TYPE_CHECKING:
    from radar.core.models.domain import Domain


class Technology(Base, TimestampMixin):
    """A tracked capability, not a product and not a company.

    ``scope_note`` is required rather than optional, and that is the point of
    the table. "Humanoid robots" is not a trackable subject; "general-purpose
    manipulation in unstructured environments, excluding teleoperation" is. A
    technology whose boundary is not written down cannot have a maturity stage,
    because nobody can say what the evidence is evidence *of*.
    """

    __tablename__ = "technology"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'active', 'merged', 'retired')", name="status_valid"
        ),
        CheckConstraint("status <> 'merged' OR merged_into IS NOT NULL", name="merged_has_target"),
        CheckConstraint("merged_into IS NULL OR merged_into <> id", name="merged_not_self"),
        Index("ix_technology_domain_id", "domain_id"),
        Index("ix_technology_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_technology_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain_id: Mapped[str] = mapped_column(
        ForeignKey("domain.id", ondelete="RESTRICT"), nullable=False
    )
    scope_note: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="What is and is not included. Required; see the class docstring.",
    )
    description: Mapped[str | None] = mapped_column(Text, comment="Curator-written.")
    openalex_query: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    featured: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    status: Mapped[EntityStatus] = mapped_column(Text, nullable=False, server_default="proposed")
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("technology.id", ondelete="SET NULL")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', name || ' ' || coalesce(description, ''))", persisted=True
        ),
        nullable=False,
    )

    domain: Mapped[Domain] = relationship()
    aliases: Mapped[list[TechnologyAlias]] = relationship(
        back_populates="technology", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Technology {self.slug} {self.status}>"


class TechnologyAlias(Base):
    """Surface forms that resolve to a technology.

    Extraction returns mentions as strings; resolution to an entity is
    deterministic table lookup, never a model decision (docs/04 rule G.3.2).
    This table is that lookup.
    """

    __tablename__ = "technology_alias"

    technology_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technology.id", ondelete="CASCADE"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(Text, primary_key=True)

    technology: Mapped[Technology] = relationship(back_populates="aliases")

    def __repr__(self) -> str:
        return f"<TechnologyAlias {self.alias!r}>"
