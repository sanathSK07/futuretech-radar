"""bioRxiv and medRxiv fetcher.

Reads the public details API documented at https://api.biorxiv.org/. The
endpoint takes a date interval and a cursor:

    https://api.biorxiv.org/details/biorxiv/2026-09-01/2026-09-18/0

and answers JSON with a ``collection`` of preprints and a ``messages`` block
carrying the cursor, the page count and the total.

This is the biotech half of the corpus. arXiv's q-bio categories are small and
mostly theoretical; bioRxiv is where base editing, cell-free synthesis and the
rest of the tracked biotech capabilities are actually posted.

Metadata only. bioRxiv preprints carry per-paper licences (many CC-BY, some
"no reuse"), so the licence string the API returns is stored with the document
and the full text is never fetched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import structlog

from radar.pipeline.fetchers.base import RawDocument, normalise_text
from radar.pipeline.http import SafeHttpClient

log = structlog.get_logger(__name__)

BIORXIV_API_URL = "https://api.biorxiv.org/details"

PAGE_SIZE = 100
"""The API's fixed page size; the cursor advances by this much."""

MAX_PAGES = 30
"""A ceiling on paging, so a wide window cannot spend an hour walking a server.

Reaching it is logged rather than passed over: a run that stopped early has an
incomplete window, and the next run's ``since`` must not assume otherwise.
"""


def parse_biorxiv_date(value: str | None) -> datetime | None:
    """Parse the API's YYYY-MM-DD date into an aware UTC datetime.

    The API supplies a date, not a timestamp, so this is midnight UTC on the
    posting day — precise enough for a daily job, and honest about what the
    source actually said.
    """
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        log.warning("unparseable_biorxiv_date", value=value)
        return None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def parse_authors(value: str | None) -> list[dict[str, str]]:
    """Split the API's semicolon-separated author string.

    bioRxiv returns "Smith, J.; Patel, R.; Okonkwo, A." as one field. Names are
    kept exactly as given: reformatting them would be inventing information
    about people, and the surface form is what entity resolution matches on.
    """
    if not value:
        return []
    return [{"name": name.strip()} for name in value.split(";") if name.strip()]


def parse_record(record: dict[str, Any]) -> RawDocument | None:
    """Turn one collection entry into a document, or None if unusable."""
    doi = (record.get("doi") or "").strip()
    title = normalise_text(record.get("title") or "")
    if not doi or not title:
        log.warning("biorxiv_record_missing_doi_or_title", doi=doi or None)
        return None

    abstract = record.get("abstract")
    return RawDocument(
        # The DOI, not the versioned one: bioRxiv assigns a new version to a
        # revision and keeps the DOI, so this makes a revision update one record
        # rather than creating a second.
        external_id=doi,
        url=f"https://www.biorxiv.org/content/{doi}v{record.get('version', '1')}",
        title=title,
        abstract=normalise_text(abstract) if abstract else None,
        published_at=parse_biorxiv_date(record.get("date")),
        authors=parse_authors(record.get("authors")),
        canonical_ids={"doi": doi},
        licence=(record.get("license") or None),
    )


def parse_response(payload: dict[str, Any]) -> tuple[list[RawDocument], int]:
    """Parse one page into documents and the total the server reports."""
    collection = payload.get("collection") or []
    documents = [doc for record in collection if (doc := parse_record(record)) is not None]

    total = 0
    messages = payload.get("messages") or []
    if messages and isinstance(messages[0], dict):
        try:
            total = int(messages[0].get("total", 0))
        except (TypeError, ValueError):
            total = 0
    return documents, total


class BiorxivFetcher:
    """Reads one bioRxiv or medRxiv server, optionally filtered to a category.

    The API has no category parameter, so ``category`` filters client-side. That
    means a narrow category still costs a full walk of the window — acceptable
    at one request per second for a daily job, and the alternative is no biotech
    coverage at all.
    """

    def __init__(
        self,
        client: SafeHttpClient,
        *,
        server: str = "biorxiv",
        category: str | None = None,
    ) -> None:
        self._client = client
        self._server = server
        self._category = category.strip().lower() if category else None

    def _matches(self, record_category: str | None) -> bool:
        if self._category is None:
            return True
        return (record_category or "").strip().lower() == self._category

    def discover(self, since: datetime) -> Iterator[RawDocument]:
        start = since.astimezone(UTC).date().isoformat()
        end = datetime.now(UTC).date().isoformat()

        cursor = 0
        seen = 0
        for _page in range(MAX_PAGES):
            url = f"{BIORXIV_API_URL}/{self._server}/{start}/{end}/{cursor}"
            response = self._client.get(url)
            payload = response.json()
            documents, total = parse_response(payload)
            raw_count = len(payload.get("collection") or [])

            categories = {
                (record.get("category") or "").strip().lower()
                for record in (payload.get("collection") or [])
            }
            log.info(
                "biorxiv_page",
                server=self._server,
                cursor=cursor,
                returned=raw_count,
                total=total,
                categories=len(categories),
            )

            for record, document in zip(payload.get("collection") or [], documents, strict=False):
                if self._matches(record.get("category")):
                    yield document

            seen += raw_count
            if raw_count < PAGE_SIZE or (total and seen >= total):
                return
            cursor += PAGE_SIZE
        else:
            log.warning(
                "biorxiv_page_limit_reached",
                server=self._server,
                pages=MAX_PAGES,
                note="the window was not fully walked; narrow --since",
            )
