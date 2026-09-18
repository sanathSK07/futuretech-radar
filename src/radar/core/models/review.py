"""The human review queue, and the audit trail of what reviewers did."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from radar.core.models.base import Base, uuid_pk
from radar.core.types import ReviewActionKind, ReviewReason, ReviewTaskStatus


class ReviewTask(Base):
    """Something a person needs to look at.

    ``target_id`` is an untyped UUID with ``target_type`` beside it rather than
    six nullable foreign keys. The trade is real: the database cannot enforce
    that the target exists. Six nullable columns with five always null is worse
    to query and worse to extend, and the review UI reads these one type at a
    time anyway.
    """

    __tablename__ = "review_task"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('claim', 'technology', 'organization', 'development', "
            "'assessment', 'relation', 'correction')",
            name="target_type_valid",
        ),
        CheckConstraint(
            "reason IN ('new_entity', 'high_stage', 'conflict', 'low_confidence', "
            "'ungrounded_quote', 'user_report')",
            name="reason_valid",
        ),
        CheckConstraint("status IN ('open', 'done', 'dismissed')", name="status_valid"),
        Index("ix_review_task_status_priority", "status", "priority"),
        Index("ix_review_task_target_type_target_id", "target_type", "target_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reason: Mapped[ReviewReason] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False, server_default="0")
    status: Mapped[ReviewTaskStatus] = mapped_column(Text, nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ReviewTask {self.target_type} {self.reason} {self.status}>"


class ReviewAction(Base):
    """What a reviewer did, with the values before and after.

    This is the field-level history for the whole system. Every human-edited row
    points at one of these, so "who changed this, when, from what" is answerable
    without triggers or temporal tables (docs/06 section K.3).
    """

    __tablename__ = "review_action"
    __table_args__ = (
        CheckConstraint(
            "action IN ('accept', 'edit', 'reject', 'merge', 'retract')", name="action_valid"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_task.id", ondelete="SET NULL")
    )
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[ReviewActionKind] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ReviewAction {self.action} by {self.actor_id}>"
