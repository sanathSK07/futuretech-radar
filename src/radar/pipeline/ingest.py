"""Ingestion: poll sources, record what was found, insert only what is new."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from radar.core.models import FetchRun, SourceDocument
from radar.core.settings import Settings
from radar.core.types import FetchStatus, SourceKind
from radar.pipeline.fetchers.arxiv import ARXIV_API_URL, ArxivFetcher
from radar.pipeline.fetchers.arxiv_oai import ARXIV_OAI_URL, ArxivOaiFetcher
from radar.pipeline.fetchers.base import Fetcher, RawDocument
from radar.pipeline.fetchers.biorxiv import BIORXIV_API_URL, BiorxivFetcher
from radar.pipeline.fetchers.rss import RssFetcher
from radar.pipeline.http import SafeHttpClient
from radar.pipeline.ratelimit import LimiterRegistry, MinIntervalLimiter
from radar.pipeline.registry import Registry, SourceSpec

log = structlog.get_logger(__name__)


class UnsupportedSourceKindError(NotImplementedError):
    """No fetcher exists for this source kind yet."""


def host_for(spec: SourceSpec) -> str:
    """The host a source's requests go to, used to share a rate limiter."""
    if spec.kind == SourceKind.ARXIV_CATEGORY:
        return str(urlsplit(ARXIV_API_URL).hostname)
    if spec.kind == SourceKind.ARXIV_OAI:
        return str(urlsplit(ARXIV_OAI_URL).hostname)
    if spec.kind == SourceKind.BIORXIV:
        return str(urlsplit(BIORXIV_API_URL).hostname)
    url = spec.params.get("url")
    if isinstance(url, str) and url:
        return str(urlsplit(url).hostname)
    raise UnsupportedSourceKindError(f"cannot determine a host for source {spec.id!r}")


def build_fetcher(spec: SourceSpec, client: SafeHttpClient) -> Fetcher:
    """Return the fetcher for a source kind."""
    if spec.kind == SourceKind.ARXIV_CATEGORY:
        return ArxivFetcher(client, category=str(spec.params["category"]))
    if spec.kind == SourceKind.ARXIV_OAI:
        return ArxivOaiFetcher(client, set_spec=str(spec.params["set"]))
    if spec.kind == SourceKind.RSS:
        return RssFetcher(client, url=str(spec.params["url"]))
    if spec.kind == SourceKind.BIORXIV:
        category = spec.params.get("category")
        return BiorxivFetcher(
            client,
            server=str(spec.params.get("server", "biorxiv")),
            category=str(category) if category else None,
        )
    raise UnsupportedSourceKindError(
        f"no fetcher for kind {spec.kind!r} yet (source {spec.id!r}); it arrives in a later sprint"
    )


def insert_document(
    session: Session,
    *,
    source_id: str,
    fetch_run_id: object,
    document: RawDocument,
    retrieved_at: datetime,
) -> bool:
    """Insert one document, doing nothing if it is already stored.

    Returns True when a row was created. ON CONFLICT DO NOTHING against the
    (source_id, external_id) unique constraint is what makes a re-run of the same
    window insert zero rows, rather than raising or duplicating.
    """
    statement = (
        pg_insert(SourceDocument)
        .values(
            source_id=source_id,
            external_id=document.external_id,
            canonical_ids=document.canonical_ids,
            url=document.url,
            title=document.title,
            authors=document.authors or None,
            published_at=document.published_at,
            retrieved_at=retrieved_at,
            abstract=document.abstract,
            content_hash=document.content_hash,
            licence=document.licence,
            fetch_run_id=fetch_run_id,
        )
        .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
        .returning(SourceDocument.id)
    )
    return session.execute(statement).scalar_one_or_none() is not None


def ingest_source(
    session: Session,
    spec: SourceSpec,
    client: SafeHttpClient,
    *,
    since: datetime,
    limit: int | None = None,
) -> FetchRun:
    """Poll one source and record the outcome.

    Errors are caught and recorded on the run rather than raised, so one broken
    feed cannot abort a nightly ingestion covering the rest.
    """
    started = datetime.now(UTC)
    run = FetchRun(source_id=spec.id, started_at=started, status=FetchStatus.RUNNING)
    session.add(run)
    session.flush()

    fetched = 0
    created = 0
    try:
        fetcher = build_fetcher(spec, client)
        for document in fetcher.discover(since):
            fetched += 1
            if insert_document(
                session,
                source_id=spec.id,
                fetch_run_id=run.id,
                document=document,
                retrieved_at=datetime.now(UTC),
            ):
                created += 1
            if limit is not None and fetched >= limit:
                log.info("ingest_limit_reached", source_id=spec.id, limit=limit)
                break
        run.status = FetchStatus.OK
    except Exception as exc:
        # Deliberately broad: one broken feed must not abort a run covering the rest.
        run.status = FetchStatus.ERROR
        run.error = f"{type(exc).__name__}: {exc}"
        # Formatted rather than passed as exc_info: the console renderer raises
        # on exceptions whose args are not plain strings (ExpatError is one),
        # which would turn a single bad feed into a crashed run.
        log.error("ingest_failed", source_id=spec.id, error=run.error)
    finally:
        run.fetched_count = fetched
        run.new_count = created
        run.finished_at = datetime.now(UTC)
        session.flush()

    log.info(
        "ingest_source_done",
        source_id=spec.id,
        status=run.status,
        fetched=fetched,
        new=created,
    )
    return run


ClientFactory = Callable[[MinIntervalLimiter], SafeHttpClient]


DEFAULT_SETTLE_SECONDS = 60.0
"""How long to wait before retrying the sources that failed.

Three consecutive live runs showed arXiv's 406 shedding windows outlasting a
six-attempt backoff inside a single source, while the same request succeeded
minutes later in the next run. Waiting once, after every other source has been
polled, costs a minute and recovers what patience inside the source could not.
"""


def ingest_all(
    session: Session,
    registry: Registry,
    settings: Settings,
    *,
    since: datetime,
    only: str | None = None,
    limit: int | None = None,
    client_factory: ClientFactory | None = None,
    retry_failed: bool = True,
    settle_seconds: float = DEFAULT_SETTLE_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> list[FetchRun]:
    """Poll every active source (or one named source) and return the runs.

    Sources that failed are polled once more at the end, after a pause. This is
    not belt-and-braces: arXiv sheds load in windows that outlast any sensible
    per-request backoff, and the evidence is direct — across three live runs,
    every category that failed has also succeeded, one of them on the sixth
    attempt of the same URL with identical headers. Retrying inside the source
    only lengthens the wait while the window is still open; coming back after
    the other sixteen sources have been polled costs nothing extra and finds it
    closed.

    ``client_factory`` exists so tests can drive this with a mock transport;
    production leaves it unset and gets a real rate-limited client.
    """
    if client_factory is None:

        def client_factory(limiter: MinIntervalLimiter) -> SafeHttpClient:
            return SafeHttpClient(contact=settings.crawler_contact, limiter=limiter)

    wait = sleep or time.sleep
    specs = [registry.get(only)] if only else registry.active_sources
    limiters = LimiterRegistry()

    def poll(spec: SourceSpec) -> FetchRun | None:
        try:
            host = host_for(spec)
        except UnsupportedSourceKindError:
            log.warning("skipping_source_without_host", source_id=spec.id)
            return None
        limiter = limiters.for_host(host, spec.rate_limit.min_interval_seconds)
        with client_factory(limiter) as client:
            run = ingest_source(session, spec, client, since=since, limit=limit)
        # Commit per source so a later failure cannot discard earlier work.
        session.commit()
        return run

    runs: list[FetchRun] = []
    by_source: dict[str, FetchRun] = {}
    for spec in specs:
        if not spec.active and only is None:
            continue
        run = poll(spec)
        if run is not None:
            runs.append(run)
            by_source[spec.id] = run

    failed = [
        spec
        for spec in specs
        if by_source.get(spec.id) is not None and by_source[spec.id].status == FetchStatus.ERROR
    ]
    if retry_failed and failed:
        log.info(
            "retrying_failed_sources",
            count=len(failed),
            settle_seconds=settle_seconds,
            source_ids=[spec.id for spec in failed],
        )
        wait(settle_seconds)
        for spec in failed:
            run = poll(spec)
            if run is not None:
                runs.append(run)
                if run.status == FetchStatus.OK:
                    log.info("source_recovered_on_retry", source_id=spec.id)

    return runs


def parse_since(value: str, *, now: datetime | None = None) -> datetime:
    """Turn '1d', '12h', '30m' or an ISO date into an aware UTC datetime."""
    reference = now or datetime.now(UTC)
    text = value.strip().lower()
    units = {"d": "days", "h": "hours", "m": "minutes", "w": "weeks"}
    if len(text) > 1 and text[-1] in units and text[:-1].isdigit():
        return reference - timedelta(**{units[text[-1]]: int(text[:-1])})
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"could not read {value!r} as a window; use 1d, 12h, 30m, 2w or an ISO date"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
