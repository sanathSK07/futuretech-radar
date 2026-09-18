"""Source registry: one row per feed we poll, mirroring sources.yaml."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.core.models.base import Base, TimestampMixin
from radar.core.types import SourceKind, SourceTier

if TYPE_CHECKING:
    from radar.core.models.fetch_run import FetchRun
    from radar.core.models.source_document import SourceDocument


class Source(Base, TimestampMixin):
    """A publisher or feed, with the reliability tier that governs what its
    documents may support.

    The primary key is a human-readable slug ("arxiv-cs-ro") rather than a UUID,
    because sources are declared by hand in sources.yaml and reviewed in pull
    requests; a readable key makes those diffs legible.
    """

    __tablename__ = "source"
    __table_args__ = (
        CheckConstraint(
            "tier IN ('T1', 'T2', 'T3', 'T4')",
            name="tier_valid",
        ),
        CheckConstraint(
            "kind IN ('arxiv_category', 'biorxiv', 'rss', 'openalex', 'ror')",
            name="kind_valid",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[SourceKind] = mapped_column(Text, nullable=False)
    tier: Mapped[SourceTier] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    schedule: Mapped[str] = mapped_column(Text, nullable=False, server_default="daily")
    licence_note: Mapped[str | None] = mapped_column(Text)
    domains: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    fetch_runs: Mapped[list[FetchRun]] = relationship(back_populates="source")
    documents: Mapped[list[SourceDocument]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"<Source {self.id} tier={self.tier}>"
