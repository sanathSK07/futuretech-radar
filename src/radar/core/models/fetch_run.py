"""One recorded poll of one source."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.core.models.base import Base, uuid_pk
from radar.core.types import FetchStatus

if TYPE_CHECKING:
    from radar.core.models.source import Source


class FetchRun(Base):
    """Audit record for a source poll.

    Errors are recorded per source rather than raised, so one broken feed cannot
    abort a nightly ingestion covering forty others.
    """

    __tablename__ = "fetch_run"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'ok', 'error')", name="status_valid"),
        CheckConstraint("fetched_count >= 0 AND new_count >= 0", name="counts_non_negative"),
        CheckConstraint("new_count <= fetched_count", name="new_not_above_fetched"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[FetchStatus] = mapped_column(Text, nullable=False)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="fetch_runs")

    def __repr__(self) -> str:
        return f"<FetchRun {self.source_id} {self.status} new={self.new_count}>"
