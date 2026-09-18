"""The six technology domains the MVP tracks."""

from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from radar.core.models.base import Base, TimestampMixin


class Domain(Base, TimestampMixin):
    """A tracked field, such as 'quantum' or 'robotics'.

    A text primary key rather than a UUID: domains are a small, curated,
    human-readable set that appears in URLs and in sources.yaml, and a slug
    makes those joins legible without a lookup.
    """

    __tablename__ = "domain"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Domain {self.id}>"
