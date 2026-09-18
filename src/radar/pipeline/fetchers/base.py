"""The contract every fetcher implements."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

_WHITESPACE = re.compile(r"\s+")


def normalise_text(value: str) -> str:
    """Collapse whitespace and normalise Unicode for stable comparison.

    Applied before hashing so that a feed re-wrapping an abstract, or switching
    between composed and decomposed accents, does not read as new content.
    """
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", value)).strip()


def content_hash(title: str, abstract: str | None) -> str:
    """A stable fingerprint of a document's substance.

    Deliberately excludes the URL and the source, so the same press release
    published by two outlets hashes identically and can be linked as a duplicate
    (see the note on content_hash in docs/06 section K.3).
    """
    payload = f"{normalise_text(title)}\n{normalise_text(abstract or '')}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawDocument:
    """A document as a fetcher found it, before it reaches the database."""

    external_id: str
    url: str
    title: str
    abstract: str | None = None
    published_at: datetime | None = None
    authors: list[dict[str, Any]] = field(default_factory=list)
    canonical_ids: dict[str, str] = field(default_factory=dict)
    licence: str | None = None

    @property
    def content_hash(self) -> str:
        return content_hash(self.title, self.abstract)


@runtime_checkable
class Fetcher(Protocol):
    """Discovers documents published by one source since a point in time.

    Implementations must be idempotent: calling ``discover`` twice for the same
    window yields the same ``external_id`` values, which is what makes a re-run
    insert nothing new.
    """

    def discover(self, since: datetime) -> Iterator[RawDocument]:
        """Yield documents published at or after ``since``."""
        ...
