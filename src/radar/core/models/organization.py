"""Organisations, resolved to ROR identifiers where one exists."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Index, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from radar.core.models.base import Base, TimestampMixin, uuid_pk
from radar.core.types import EntityStatus, OrganizationKind


class Organization(Base, TimestampMixin):
    """A university, company, lab, funder or regulator.

    ``ror_id`` is unique but nullable: the Research Organization Registry covers
    academia and public bodies well and young companies not at all. A startup
    with no ROR record is still a real developer, so the column cannot be
    required — but two rows may not claim the same ROR identifier.
    """

    __tablename__ = "organization"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'active', 'merged', 'retired')", name="status_valid"
        ),
        CheckConstraint(
            "kind IS NULL OR kind IN ('university', 'company', 'government', 'lab', "
            "'nonprofit', 'consortium')",
            name="kind_valid",
        ),
        Index("ix_organization_name", "name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    ror_id: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[OrganizationKind | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text, comment="ISO 3166-1 alpha-2.")
    website: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    status: Mapped[EntityStatus] = mapped_column(Text, nullable=False, server_default="proposed")

    def __repr__(self) -> str:
        return f"<Organization {self.name!r} {self.ror_id or 'no-ror'}>"
