"""Schema v0 behaviour, exercised against a migrated PostgreSQL database.

These tests encode the guarantees later sprints depend on: re-running an
ingestion must not duplicate rows, duplicate content must be recordable rather
than rejected, and full-text and vector search must actually work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from radar.core.models import FetchRun, Source, SourceDocument
from radar.core.types import DocumentLifecycle, FetchStatus, SourceKind, SourceTier

pytestmark = pytest.mark.db


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


class TestSource:
    def test_round_trips(self, session: Session) -> None:
        make_source(session)
        loaded = session.get(Source, "arxiv-cs-ro")
        assert loaded is not None
        assert loaded.tier == SourceTier.T1
        assert loaded.params == {"category": "cs.RO"}
        assert loaded.domains == ["robotics"]
        assert loaded.active is True
        assert loaded.schedule == "daily"

    def test_rejects_an_invalid_tier(self, session: Session) -> None:
        session.add(
            Source(id="bad", name="Bad", kind=SourceKind.RSS, tier="T9")  # type: ignore[arg-type]
        )
        with pytest.raises(IntegrityError, match="tier_valid"):
            session.flush()

    def test_rejects_an_unknown_kind(self, session: Session) -> None:
        session.add(
            Source(id="bad", name="Bad", kind="scrape", tier=SourceTier.T3)  # type: ignore[arg-type]
        )
        with pytest.raises(IntegrityError, match="kind_valid"):
            session.flush()


class TestFetchRun:
    def test_records_a_successful_poll(self, session: Session) -> None:
        source = make_source(session)
        run = FetchRun(
            source_id=source.id,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status=FetchStatus.OK,
            fetched_count=30,
            new_count=4,
        )
        session.add(run)
        session.flush()
        assert isinstance(run.id, uuid.UUID)
        assert run.source.id == source.id

    def test_rejects_more_new_than_fetched(self, session: Session) -> None:
        source = make_source(session)
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=datetime.now(UTC),
                status=FetchStatus.OK,
                fetched_count=2,
                new_count=5,
            )
        )
        with pytest.raises(IntegrityError, match="new_not_above_fetched"):
            session.flush()

    def test_rejects_negative_counts(self, session: Session) -> None:
        source = make_source(session)
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=datetime.now(UTC),
                status=FetchStatus.ERROR,
                fetched_count=-1,
            )
        )
        with pytest.raises(IntegrityError, match="counts_non_negative"):
            session.flush()


class TestSourceDocumentIdempotency:
    def test_same_source_and_external_id_cannot_be_inserted_twice(self, session: Session) -> None:
        """The guarantee Task 3 rests on: re-running a day's fetch inserts nothing new."""
        source = make_source(session)
        make_document(session, source, "arXiv:2609.00001")
        session.add(
            SourceDocument(
                source_id=source.id,
                external_id="arXiv:2609.00001",
                url="https://arxiv.org/abs/2609.00001v2",
                title="Same paper, fetched again",
                retrieved_at=datetime.now(UTC),
                content_hash="different-hash",
            )
        )
        with pytest.raises(IntegrityError, match="uq_source_document_source_id_external_id"):
            session.flush()

    def test_the_same_external_id_from_a_different_source_is_allowed(
        self, session: Session
    ) -> None:
        arxiv = make_source(session, "arxiv-cs-ro")
        news = make_source(session, "mit-news", kind=SourceKind.RSS, tier=SourceTier.T2)
        make_document(session, arxiv, "shared-id")
        make_document(session, news, "shared-id")
        count = session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.external_id == "shared-id")
        )
        assert count == 2

    def test_identical_content_from_two_sources_is_recorded_not_rejected(
        self, session: Session
    ) -> None:
        """A syndicated press release must become a duplicate row, not an error."""
        wire = make_source(session, "eurekalert", kind=SourceKind.RSS, tier=SourceTier.T2)
        uni = make_source(session, "mit-news", kind=SourceKind.RSS, tier=SourceTier.T2)
        original = make_document(session, wire, "wire-1", content_hash="identical")
        copy = make_document(
            session,
            uni,
            "uni-1",
            content_hash="identical",
            lifecycle=DocumentLifecycle.DUPLICATE,
            duplicate_of=original.id,
        )
        session.flush()
        assert copy.duplicate_target is not None
        assert copy.duplicate_target.id == original.id


class TestSourceDocumentConstraints:
    def test_a_document_cannot_duplicate_itself(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.duplicate_of = document.id
        document.lifecycle = DocumentLifecycle.DUPLICATE
        with pytest.raises(IntegrityError, match="duplicate_not_self"):
            session.flush()

    def test_duplicate_lifecycle_requires_a_target(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.lifecycle = DocumentLifecycle.DUPLICATE
        with pytest.raises(IntegrityError, match="duplicate_has_target"):
            session.flush()

    def test_rejects_an_unknown_lifecycle(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.lifecycle = "archived"  # type: ignore[assignment]
        with pytest.raises(IntegrityError, match="lifecycle_valid"):
            session.flush()

    def test_rejects_an_invalid_tier_override(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.tier_override = "T7"  # type: ignore[assignment]
        with pytest.raises(IntegrityError, match="tier_override_valid"):
            session.flush()

    def test_a_source_with_documents_cannot_be_deleted(self, session: Session) -> None:
        """Documents are evidence; deleting a source must not silently orphan them."""
        source = make_source(session)
        make_document(session, source)
        session.delete(source)
        with pytest.raises(IntegrityError):
            session.flush()


class TestEffectiveTier:
    def test_defaults_to_the_source_tier(self, session: Session) -> None:
        source = make_source(session, tier=SourceTier.T2)
        document = make_document(session, source)
        assert document.effective_tier == SourceTier.T2

    def test_a_reviewer_override_wins(self, session: Session) -> None:
        source = make_source(session, tier=SourceTier.T3)
        document = make_document(session, source, tier_override=SourceTier.T1)
        assert document.effective_tier == SourceTier.T1


class TestSearch:
    def test_the_search_vector_is_generated_from_title_and_abstract(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        session.flush()
        session.refresh(document)
        assert document.search_tsv
        # tsvector stores stemmed lexemes, so "laundry" is indexed as "laundri";
        # match through a tsquery rather than asserting on the raw string.
        assert "laundri" in document.search_tsv
        matched = session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(
                SourceDocument.id == document.id,
                SourceDocument.search_tsv.op("@@")(func.websearch_to_tsquery("english", "laundry")),
            )
        )
        assert matched == 1

    def test_full_text_search_finds_a_document(self, session: Session) -> None:
        source = make_source(session)
        make_document(session, source)
        make_document(
            session,
            source,
            "arXiv:2609.00002",
            title="Superconducting magnet reaches 20 tesla",
            abstract="A high-temperature superconducting magnet for compact fusion.",
        )
        hits = session.scalars(
            select(SourceDocument).where(
                SourceDocument.search_tsv.op("@@")(func.websearch_to_tsquery("english", "fusion"))
            )
        ).all()
        assert len(hits) == 1
        assert "magnet" in hits[0].title

    def test_the_search_vector_follows_an_edit(self, session: Session) -> None:
        source = make_source(session)
        document = make_document(session, source)
        document.title = "Quantum error correction below threshold"
        session.flush()
        session.refresh(document)
        assert "quantum" in document.search_tsv
        assert "dexter" not in document.search_tsv  # the old title is gone


class TestEmbeddings:
    def test_an_embedding_round_trips(self, session: Session) -> None:
        source = make_source(session)
        vector = [0.1] * 384
        document = make_document(session, source, embedding=vector)
        session.flush()
        session.refresh(document)
        assert document.embedding is not None
        assert len(document.embedding) == 384

    def test_a_wrong_sized_embedding_is_rejected(self, session: Session) -> None:
        source = make_source(session)
        # Built inline rather than via the helper, which flushes: the failure has
        # to happen inside the raises block.
        session.add(
            SourceDocument(
                source_id=source.id,
                external_id="wrong-size",
                url="https://example.org/1",
                title="Wrong sized embedding",
                retrieved_at=datetime.now(UTC),
                content_hash="h",
                embedding=[0.1] * 16,
            )
        )
        with pytest.raises(DataError, match="expected 384 dimensions"):
            session.flush()

    def test_cosine_distance_orders_nearest_first(self, session: Session) -> None:
        """The query shape deduplication and semantic search will both use."""
        source = make_source(session)
        query = [1.0] + [0.0] * 383
        near = [0.99, 0.01] + [0.0] * 382
        far = [0.0] * 383 + [1.0]
        make_document(session, source, "near", embedding=near)
        make_document(session, source, "far", embedding=far)
        session.flush()

        ordered = session.scalars(
            select(SourceDocument)
            .where(SourceDocument.embedding.is_not(None))
            .order_by(SourceDocument.embedding.cosine_distance(query))
        ).all()
        assert [d.external_id for d in ordered] == ["near", "far"]


class TestMigrationState:
    def test_the_database_is_at_the_expected_revision(self, session: Session) -> None:
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "0001"

    def test_pgvector_is_installed(self, session: Session) -> None:
        installed = session.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
        assert installed == 1
