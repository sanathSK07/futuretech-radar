"""Fixtures shared by the database tests.

These live here rather than in one test module so that a new test file can
build a small corpus without importing another test file, which pytest allows
and which makes collection order matter in ways nobody wants to debug.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from radar.core.models import Source, SourceDocument
from radar.core.types import SourceKind, SourceTier


def make_source(session: Session, source_id: str = "arxiv-cs-ro", **kwargs: object) -> Source:
    defaults: dict[str, object] = {
        "id": source_id,
        "name": "arXiv cs.RO (Robotics)",
        "kind": SourceKind.ARXIV_CATEGORY,
        "tier": SourceTier.T1,
        "params": {"category": "cs.RO"},
        "domains": ["robotics"],
        "licence_note": "metadata CC0; link only",
    }
    defaults.update(kwargs)
    source = Source(**defaults)
    session.add(source)
    session.flush()
    return source


def make_document(
    session: Session, source: Source, external_id: str = "arXiv:2609.00001", **kwargs: object
) -> SourceDocument:
    defaults: dict[str, object] = {
        "source_id": source.id,
        "external_id": external_id,
        "url": f"https://arxiv.org/abs/{external_id}",
        "title": "Learning dexterous manipulation from human video",
        "abstract": "We demonstrate a robot hand folding laundry autonomously.",
        "retrieved_at": datetime.now(UTC),
        "content_hash": "hash-" + external_id,
    }
    defaults.update(kwargs)
    document = SourceDocument(**defaults)
    session.add(document)
    session.flush()
    return document
