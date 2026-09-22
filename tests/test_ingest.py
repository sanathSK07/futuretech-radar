"""Ingestion, and the guarantee the whole daily job rests on: re-running is free.

If a re-run duplicated documents, every downstream count, dedup decision and
maturity assessment would be built on inflated evidence. These tests exist to
make that failure impossible to ship unnoticed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.core.models import FetchRun, Source, SourceDocument
from radar.core.settings import Settings
from radar.core.types import FetchStatus, SourceKind, SourceTier
from radar.pipeline.fetchers.base import RawDocument
from radar.pipeline.fetchers.rss import RssFetcher
from radar.pipeline.http import SafeHttpClient
from radar.pipeline.ingest import (
    UnsupportedSourceKindError,
    build_fetcher,
    host_for,
    ingest_all,
    ingest_source,
    insert_document,
    parse_since,
)
from radar.pipeline.registry import Registry, SourceSpec, sync_registry

FIXTURES = Path(__file__).parent / "fixtures"

# Every test here talks to a mock transport, so no real DNS is wanted.


@pytest.fixture(autouse=True)
def _no_real_dns(public_dns: None) -> None:
    """Route hostname resolution through the hermetic fixture."""


@pytest.fixture
def feed_xml() -> str:
    return (FIXTURES / "arxiv_cs_ro.xml").read_text(encoding="utf-8")


def rss_spec(source_id: str = "mit-news") -> SourceSpec:
    return SourceSpec.model_validate(
        {
            "id": source_id,
            "name": "MIT News",
            "kind": SourceKind.RSS,
            "tier": SourceTier.T2,
            "params": {"url": "https://news.mit.edu/rss/research"},
        }
    )


def arxiv_spec(source_id: str = "arxiv-cs-ro") -> SourceSpec:
    return SourceSpec.model_validate(
        {
            "id": source_id,
            "name": "arXiv cs.RO",
            "kind": SourceKind.ARXIV_CATEGORY,
            "tier": SourceTier.T1,
            "params": {"category": "cs.RO"},
            "domains": ["robotics"],
            "licence": "metadata CC0",
        }
    )


def client_serving(body: str, *, status: int = 200) -> SafeHttpClient:
    """A client that always answers the same way.

    max_attempts=1 because these tests assert on how ingestion records a
    failure, not on retry behaviour; retries are covered in test_http.py and
    would otherwise make this suite sleep through real backoff.
    """
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    return SafeHttpClient(
        contact="test@example.org",
        client=httpx.Client(transport=transport),
        max_attempts=1,
    )


def count_documents(session: Session, source_id: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.source_id == source_id)
        )
        or 0
    )


class TestParseSince:
    def test_relative_windows(self) -> None:
        now = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
        assert parse_since("1d", now=now) == now - timedelta(days=1)
        assert parse_since("12h", now=now) == now - timedelta(hours=12)
        assert parse_since("30m", now=now) == now - timedelta(minutes=30)
        assert parse_since("2w", now=now) == now - timedelta(weeks=2)

    def test_an_iso_date(self) -> None:
        assert parse_since("2026-09-01") == datetime(2026, 9, 1, tzinfo=UTC)

    def test_nonsense_is_rejected_with_guidance(self) -> None:
        with pytest.raises(ValueError, match="use 1d, 12h"):
            parse_since("last tuesday")


class TestHostAndFetcherSelection:
    def test_every_arxiv_category_maps_to_one_host(self) -> None:
        """This is what lets the eleven arXiv sources share a single limiter."""
        assert host_for(arxiv_spec("arxiv-cs-ro")) == "export.arxiv.org"
        assert host_for(arxiv_spec("arxiv-quant-ph")) == "export.arxiv.org"

    def test_a_feed_source_maps_to_its_own_host(self) -> None:
        """Each newsroom gets its own limiter; they are unrelated servers."""
        assert host_for(rss_spec()) == "news.mit.edu"

    def test_biorxiv_sources_share_one_host(self) -> None:
        biorxiv = SourceSpec.model_validate(
            {
                "id": "biorxiv-synbio",
                "name": "bioRxiv synthetic biology",
                "kind": SourceKind.BIORXIV,
                "tier": SourceTier.T1,
                "params": {"category": "synthetic biology"},
            }
        )
        assert host_for(biorxiv) == "api.biorxiv.org"

    def test_each_kind_builds_its_own_fetcher(self) -> None:
        assert isinstance(build_fetcher(rss_spec(), client_serving("<rss/>")), RssFetcher)

    def test_an_unbuilt_fetcher_fails_clearly(self) -> None:
        """OpenAlex and ROR are declared in the registry and arrive later."""
        openalex = SourceSpec.model_validate(
            {
                "id": "openalex-concepts",
                "name": "OpenAlex",
                "kind": SourceKind.OPENALEX,
                "tier": SourceTier.T1,
                "params": {"url": "https://api.openalex.org/works"},
            }
        )
        with pytest.raises(UnsupportedSourceKindError, match="later sprint"):
            build_fetcher(openalex, client_serving("{}"))


@pytest.mark.db
class TestIdempotency:
    """Sprint 0's acceptance criterion."""

    def test_re_running_the_same_window_inserts_nothing_new(
        self, session: Session, feed_xml: str
    ) -> None:
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        # Early enough to include all three fixture entries.
        since = datetime(2026, 8, 1, tzinfo=UTC)

        first = ingest_source(session, spec, client_serving(feed_xml), since=since)
        assert first.status == FetchStatus.OK
        assert first.new_count == 3
        assert count_documents(session, spec.id) == 3

        second = ingest_source(session, spec, client_serving(feed_xml), since=since)
        assert second.status == FetchStatus.OK
        assert second.fetched_count == 3, "the source was polled again"
        assert second.new_count == 0, "but nothing new was stored"
        assert count_documents(session, spec.id) == 3

    def test_a_third_run_is_still_stable(self, session: Session, feed_xml: str) -> None:
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        since = datetime(2026, 8, 1, tzinfo=UTC)
        for _ in range(3):
            ingest_source(session, spec, client_serving(feed_xml), since=since)
        assert count_documents(session, spec.id) == 3

    def test_a_revised_paper_does_not_become_a_second_document(
        self, session: Session, feed_xml: str
    ) -> None:
        """v2 of a paper shares the versionless id, so it updates rather than duplicates."""
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        since = datetime(2026, 8, 1, tzinfo=UTC)
        ingest_source(session, spec, client_serving(feed_xml), since=since)

        revised = feed_xml.replace("2609.01234v2", "2609.01234v3")
        ingest_source(session, spec, client_serving(revised), since=since)

        assert count_documents(session, spec.id) == 3

    def test_two_sources_may_each_hold_the_same_paper(
        self, session: Session, feed_xml: str
    ) -> None:
        """Cross-source duplicates are recorded, not rejected (docs/06 K.3)."""
        first = arxiv_spec("arxiv-cs-ro")
        second = arxiv_spec("arxiv-cs-lg")
        sync_registry(session, Registry(sources=[first, second]))
        since = datetime(2026, 8, 1, tzinfo=UTC)

        ingest_source(session, first, client_serving(feed_xml), since=since)
        ingest_source(session, second, client_serving(feed_xml), since=since)

        assert count_documents(session, first.id) == 3
        assert count_documents(session, second.id) == 3

        hashes = session.scalars(
            select(SourceDocument.content_hash).where(SourceDocument.external_id == "2609.01234")
        ).all()
        assert len(hashes) == 2
        assert hashes[0] == hashes[1], "identical content must hash identically"


@pytest.mark.db
class TestIngestSource:
    def test_it_records_what_it_stored(self, session: Session, feed_xml: str) -> None:
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        ingest_source(
            session, spec, client_serving(feed_xml), since=datetime(2026, 8, 1, tzinfo=UTC)
        )

        document = session.scalars(
            select(SourceDocument).where(SourceDocument.external_id == "2609.01234")
        ).one()
        assert document.title.startswith("Dexterous In-Hand Manipulation")
        assert document.url == "https://arxiv.org/abs/2609.01234"
        assert document.canonical_ids["doi"] == "10.1109/TRO.2026.1234567"
        assert document.published_at == datetime(2026, 9, 16, 18, 2, 11, tzinfo=UTC)
        assert document.fetch_run_id is not None
        assert document.effective_tier == SourceTier.T1

    def test_the_publication_window_is_respected(self, session: Session, feed_xml: str) -> None:
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        run = ingest_source(
            session, spec, client_serving(feed_xml), since=datetime(2026, 9, 10, tzinfo=UTC)
        )
        assert run.new_count == 2, "the August entry is outside the window"

    def test_a_limit_stops_early(self, session: Session, feed_xml: str) -> None:
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        run = ingest_source(
            session,
            spec,
            client_serving(feed_xml),
            since=datetime(2026, 9, 1, tzinfo=UTC),
            limit=1,
        )
        assert run.fetched_count == 1
        assert count_documents(session, spec.id) == 1

    def test_a_failing_source_is_recorded_not_raised(self, session: Session) -> None:
        """One broken feed must not abort a run covering forty others."""
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        run = ingest_source(
            session,
            spec,
            client_serving("upstream exploded", status=503),
            since=datetime(2026, 9, 1, tzinfo=UTC),
        )
        assert run.status == FetchStatus.ERROR
        assert run.error is not None
        assert "503" in run.error
        assert run.finished_at is not None

    def test_malformed_xml_is_recorded_as_an_error(self, session: Session) -> None:
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        run = ingest_source(
            session,
            spec,
            client_serving("<feed><entry>truncated"),
            since=datetime(2026, 9, 1, tzinfo=UTC),
        )
        assert run.status == FetchStatus.ERROR

    def test_every_run_is_auditable(self, session: Session, feed_xml: str) -> None:
        spec = arxiv_spec()
        sync_registry(session, Registry(sources=[spec]))
        ingest_source(
            session, spec, client_serving(feed_xml), since=datetime(2026, 9, 1, tzinfo=UTC)
        )
        runs = session.scalars(select(FetchRun).where(FetchRun.source_id == spec.id)).all()
        assert len(runs) == 1
        assert runs[0].started_at is not None
        assert runs[0].finished_at is not None


@pytest.mark.db
class TestInsertDocument:
    def test_it_reports_whether_a_row_was_created(self, session: Session) -> None:
        sync_registry(session, Registry(sources=[arxiv_spec()]))
        document = RawDocument(
            external_id="2609.00001",
            url="https://arxiv.org/abs/2609.00001",
            title="A paper",
            abstract="An abstract.",
        )
        now = datetime.now(UTC)
        assert (
            insert_document(
                session,
                source_id="arxiv-cs-ro",
                fetch_run_id=None,
                document=document,
                retrieved_at=now,
            )
            is True
        )
        assert (
            insert_document(
                session,
                source_id="arxiv-cs-ro",
                fetch_run_id=None,
                document=document,
                retrieved_at=now,
            )
            is False
        )

    def test_a_source_must_exist_first(self, session: Session) -> None:
        document = RawDocument(external_id="x", url="https://example.org/x", title="Orphan")
        with pytest.raises(Exception, match=r"foreign key|violates"):
            insert_document(
                session,
                source_id="never-registered",
                fetch_run_id=None,
                document=document,
                retrieved_at=datetime.now(UTC),
            )


def test_a_source_row_is_required_for_documents(session: Session) -> None:
    assert session.get(Source, "does-not-exist") is None


@pytest.mark.db
class TestIngestAll:
    """The path the CLI actually takes."""

    def _settings(self) -> Settings:
        return Settings(
            _env_file=None,  # type: ignore[call-arg]
            database_url="postgresql+psycopg://u:p@localhost:5433/radar",
            crawler_contact="test@example.org",
        )

    def test_it_polls_every_active_source(self, session: Session, feed_xml: str) -> None:
        registry = Registry(
            sources=[
                arxiv_spec("arxiv-cs-ro"),
                arxiv_spec("arxiv-cs-lg"),
                SourceSpec.model_validate(
                    {
                        "id": "mit-news",
                        "name": "MIT News",
                        "kind": SourceKind.RSS,
                        "tier": SourceTier.T2,
                        "params": {"url": "https://news.mit.edu/rss/research"},
                        "active": False,
                    }
                ),
            ]
        )
        sync_registry(session, registry)

        runs = ingest_all(
            session,
            registry,
            self._settings(),
            since=datetime(2026, 8, 1, tzinfo=UTC),
            client_factory=lambda limiter: client_serving(feed_xml),
        )

        assert [r.source_id for r in runs] == ["arxiv-cs-ro", "arxiv-cs-lg"]
        assert all(r.status == FetchStatus.OK for r in runs)
        assert sum(r.new_count for r in runs) == 6

    def test_only_selects_a_single_source(self, session: Session, feed_xml: str) -> None:
        registry = Registry(sources=[arxiv_spec("arxiv-cs-ro"), arxiv_spec("arxiv-cs-lg")])
        sync_registry(session, registry)
        runs = ingest_all(
            session,
            registry,
            self._settings(),
            since=datetime(2026, 8, 1, tzinfo=UTC),
            only="arxiv-cs-lg",
            client_factory=lambda limiter: client_serving(feed_xml),
        )
        assert [r.source_id for r in runs] == ["arxiv-cs-lg"]

    def test_re_running_everything_inserts_nothing_new(
        self, session: Session, feed_xml: str
    ) -> None:
        """The daily job, run twice: the whole point of Sprint 0 Task 3."""
        registry = Registry(sources=[arxiv_spec("arxiv-cs-ro"), arxiv_spec("arxiv-cs-lg")])
        sync_registry(session, registry)
        kwargs = {
            "since": datetime(2026, 8, 1, tzinfo=UTC),
            "client_factory": lambda limiter: client_serving(feed_xml),
        }

        first = ingest_all(session, registry, self._settings(), **kwargs)  # type: ignore[arg-type]
        second = ingest_all(session, registry, self._settings(), **kwargs)  # type: ignore[arg-type]

        assert sum(r.new_count for r in first) == 6
        assert sum(r.fetched_count for r in second) == 6, "sources were polled again"
        assert sum(r.new_count for r in second) == 0, "and nothing new was stored"

    def test_one_failing_source_does_not_stop_the_others(
        self, session: Session, feed_xml: str
    ) -> None:
        registry = Registry(sources=[arxiv_spec("arxiv-cs-ro"), arxiv_spec("arxiv-cs-lg")])
        sync_registry(session, registry)

        def factory(limiter: object) -> SafeHttpClient:
            # First call fails, the rest succeed.
            if not hasattr(factory, "called"):
                factory.called = True  # type: ignore[attr-defined]
                return client_serving("boom", status=500)
            return client_serving(feed_xml)

        runs = ingest_all(
            session,
            registry,
            self._settings(),
            since=datetime(2026, 8, 1, tzinfo=UTC),
            client_factory=factory,  # type: ignore[arg-type]
        )
        statuses = {r.source_id: r.status for r in runs}
        assert statuses["arxiv-cs-ro"] == FetchStatus.ERROR
        assert statuses["arxiv-cs-lg"] == FetchStatus.OK
