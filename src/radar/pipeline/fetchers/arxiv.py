"""arXiv fetcher.

Reads the arXiv API's Atom response, documented at
https://info.arxiv.org/help/api/user-manual.html. The terms of use require no
more than one request every three seconds on a single connection
(https://info.arxiv.org/help/api/tou.html), which the caller supplies as a
rate-limited client.

Only metadata is taken. arXiv metadata is CC0; the e-prints themselves are not
redistributable, so this fetcher never downloads or stores PDFs or source.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import urlencode
from xml.etree.ElementTree import Element

import structlog
from defusedxml import ElementTree as DefusedET

from radar.pipeline.fetchers.base import RawDocument
from radar.pipeline.http import SafeHttpClient

log = structlog.get_logger(__name__)

# HTTPS directly: the http:// form answers 301, and because the rate limiter
# runs before every redirect hop, that redirect costs a wasted three seconds on
# each page fetch. Confirmed against the live API on 2026-09-18.
ARXIV_API_URL = "https://export.arxiv.org/api/query"

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"

# arXiv caps a single request at 2,000 results; we page well below that.
PAGE_SIZE = 100
MAX_PAGES = 20

_ABS_PREFIX = re.compile(r"^https?://arxiv\.org/abs/")
_VERSION_SUFFIX = re.compile(r"v(\d+)$")


def split_arxiv_id(entry_id: str) -> tuple[str, str | None]:
    """Turn an entry <id> URL into (versionless id, version).

    ``http://arxiv.org/abs/2609.00001v2`` becomes ``("2609.00001", "v2")``.

    The versionless form is used as ``external_id`` so that a revised paper
    updates the same record rather than creating a second one; the version is
    kept in canonical_ids so a revision is still visible.
    """
    raw = _ABS_PREFIX.sub("", entry_id.strip())
    match = _VERSION_SUFFIX.search(raw)
    if match:
        return raw[: match.start()], match.group(0)
    return raw, None


def parse_atom_datetime(value: str) -> datetime | None:
    """Parse an Atom timestamp into an aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        log.warning("unparseable_date", value=value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_feed(xml_text: str) -> tuple[list[RawDocument], int]:
    """Parse an arXiv Atom feed into documents and the total result count.

    Uses defusedxml, because the response is third-party input and a stock XML
    parser is vulnerable to entity-expansion attacks (docs/07, "malicious
    content").
    """
    root: Element = DefusedET.fromstring(xml_text)

    total_element = root.find(f"{OPENSEARCH}totalResults")
    total = int(total_element.text) if total_element is not None and total_element.text else 0

    documents: list[RawDocument] = []
    for entry in root.findall(f"{ATOM}entry"):
        document = _parse_entry(entry)
        if document is not None:
            documents.append(document)
    return documents, total


def _text(element: Element, path: str) -> str | None:
    found = element.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _parse_entry(entry: Element) -> RawDocument | None:
    entry_id = _text(entry, f"{ATOM}id")
    title = _text(entry, f"{ATOM}title")
    if not entry_id or not title:
        log.warning("entry_missing_id_or_title", entry_id=entry_id)
        return None

    arxiv_id, version = split_arxiv_id(entry_id)

    authors: list[dict[str, str]] = []
    for author in entry.findall(f"{ATOM}author"):
        name = _text(author, f"{ATOM}name")
        if not name:
            continue
        record = {"name": name}
        affiliation = _text(author, f"{ARXIV_NS}affiliation")
        if affiliation:
            record["affiliation"] = affiliation
        authors.append(record)

    canonical_ids: dict[str, str] = {"arxiv": arxiv_id}
    if version:
        canonical_ids["arxiv_version"] = version
    doi = _text(entry, f"{ARXIV_NS}doi")
    if doi:
        canonical_ids["doi"] = doi

    categories = [
        term for category in entry.findall(f"{ATOM}category") if (term := category.get("term"))
    ]
    if categories:
        canonical_ids["arxiv_categories"] = ",".join(categories)
    primary = entry.find(f"{ARXIV_NS}primary_category")
    if primary is not None and primary.get("term"):
        canonical_ids["arxiv_primary_category"] = str(primary.get("term"))

    published_raw = _text(entry, f"{ATOM}published")
    published_at = parse_atom_datetime(published_raw) if published_raw else None

    # Prefer the canonical abstract page over whatever host the feed used.
    abs_url = f"https://arxiv.org/abs/{arxiv_id}"

    return RawDocument(
        external_id=arxiv_id,
        url=abs_url,
        title=" ".join(title.split()),
        abstract=(_text(entry, f"{ATOM}summary") or None),
        published_at=published_at,
        authors=list(authors),
        canonical_ids=canonical_ids,
        licence="arXiv metadata CC0; e-print under its own licence, not redistributed",
    )


class ArxivFetcher:
    """Fetches recent submissions in one arXiv category."""

    def __init__(
        self, client: SafeHttpClient, *, category: str, page_size: int = PAGE_SIZE
    ) -> None:
        if not category:
            raise ValueError("an arXiv category is required, e.g. 'cs.RO'")
        self.client = client
        self.category = category
        self.page_size = page_size

    def build_url(self, *, start: int) -> str:
        query = urlencode(
            {
                "search_query": f"cat:{self.category}",
                "start": start,
                "max_results": self.page_size,
                # Newest first, so paging can stop as soon as it passes `since`.
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        return f"{ARXIV_API_URL}?{query}"

    def discover(self, since: datetime) -> Iterator[RawDocument]:
        """Yield submissions published at or after ``since``, newest first."""
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            url = self.build_url(start=page * self.page_size)
            result = self.client.get(url)
            documents, total = parse_feed(result.text)

            if not documents:
                log.info("arxiv_page_empty", category=self.category, page=page, total=total)
                return

            for document in documents:
                if document.published_at is not None and document.published_at < since:
                    # Results are newest first, so everything after this is older.
                    log.info(
                        "arxiv_reached_window_edge",
                        category=self.category,
                        page=page,
                        since=since.isoformat(),
                    )
                    return
                if document.external_id in seen:
                    continue
                seen.add(document.external_id)
                yield document

            if (page + 1) * self.page_size >= total:
                return

        log.warning("arxiv_page_limit_reached", category=self.category, max_pages=MAX_PAGES)
