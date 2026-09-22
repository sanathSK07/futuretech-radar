"""RSS and Atom fetcher for official feeds.

This is the fetcher that gives the project the documents arXiv cannot supply.
Fusion milestones, battery deployments, regulatory approvals and product
launches are announced on lab and company newsrooms, not posted as preprints —
so without this, two of the six MVP domains have no evidence at all.

It reads both RSS 2.0 and Atom, because official feeds are split roughly evenly
between them and a source that publishes one should not need a different entry
in the registry from a source that publishes the other.

Everything here is metadata plus the feed's own summary. Full article text is
not fetched: most of these feeds are T2 (self-interested) publishers whose terms
do not permit storing the article, and the summary is enough to extract a claim
and link to the original.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from xml.etree.ElementTree import Element

import structlog
from defusedxml import ElementTree as DefusedET

from radar.pipeline.fetchers.base import RawDocument, normalise_text
from radar.pipeline.http import SafeHttpClient

log = structlog.get_logger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
DUBLIN_CORE = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"

MAX_SUMMARY_CHARACTERS = 4000
"""Summaries longer than this are truncated.

A few feeds put the entire article in the description. Storing it would make the
licence position of a T2 source much less comfortable than storing a summary,
and extraction works from the first few paragraphs regardless.
"""


class _TextExtractor(HTMLParser):
    """Strip tags from a feed summary, keeping the words.

    Feed descriptions are HTML fragments. A regex that removes anything between
    angle brackets also eats the contents of a comparison written as "a < b",
    and mangles a CDATA block; the standard library's parser handles both, and
    resolves entities while it is there.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "br", "div", "li"}:
            self._parts.append(" ")

    @property
    def text(self) -> str:
        return normalise_text("".join(self._parts))


def strip_html(value: str | None) -> str | None:
    """Return the readable text of an HTML fragment, or None if there is none."""
    if not value:
        return None
    parser = _TextExtractor()
    try:
        parser.feed(unescape(value))
        parser.close()
    except Exception:
        log.warning("unparseable_html_summary")
        return normalise_text(value) or None
    text = parser.text
    if len(text) > MAX_SUMMARY_CHARACTERS:
        text = text[:MAX_SUMMARY_CHARACTERS].rsplit(" ", 1)[0] + "…"
    return text or None


def parse_feed_datetime(value: str | None) -> datetime | None:
    """Parse a feed timestamp, trying RFC 822 then ISO 8601.

    RSS 2.0 specifies RFC 822 ("Tue, 15 Sep 2026 09:00:00 GMT"); Atom specifies
    RFC 3339. Feeds in the wild use either regardless of their format, so both
    are tried rather than trusting the element name.
    """
    if not value or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            log.warning("unparseable_feed_date", value=raw)
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _text(element: Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def _first(item: Element, *paths: str) -> Element | None:
    for path in paths:
        found = item.find(path)
        if found is not None:
            return found
    return None


def _link(item: Element) -> str | None:
    """Find the entry's URL in either dialect.

    RSS puts it in the element's text; Atom puts it in an href attribute and may
    offer several, of which the alternate link is the human-readable page.
    """
    rss_link = _text(item.find("link"))
    if rss_link:
        return rss_link
    links = item.findall(f"{ATOM}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href")
    for link in links:
        if link.get("href"):
            return link.get("href")
    return None


def _authors(item: Element) -> list[dict[str, str]]:
    names: list[str] = []
    for element in item.findall(f"{DUBLIN_CORE}creator"):
        if name := _text(element):
            names.append(name)
    for element in item.findall(f"{ATOM}author"):
        if name := _text(element.find(f"{ATOM}name")):
            names.append(name)
    if not names and (name := _text(item.find("author"))):
        names.append(name)
    return [{"name": name} for name in names]


def parse_entry(item: Element) -> RawDocument | None:
    """Turn one RSS <item> or Atom <entry> into a document.

    Returns None rather than raising when an entry has no title or no link:
    one malformed entry in a feed of forty is a data-quality event, not a reason
    to lose the other thirty-nine.
    """
    title = _text(_first(item, "title", f"{ATOM}title"))
    url = _link(item)
    if not title or not url:
        log.warning("feed_entry_missing_title_or_link", title=title, url=url)
        return None

    summary = _text(
        _first(item, f"{CONTENT}encoded", "description", f"{ATOM}summary", f"{ATOM}content")
    )
    published = parse_feed_datetime(
        _text(_first(item, "pubDate", f"{DUBLIN_CORE}date", f"{ATOM}published", f"{ATOM}updated"))
    )

    # guid, then Atom id, then the URL. A feed that supplies no identifier still
    # has to produce a stable external_id, or every run re-inserts everything.
    identifier = _text(_first(item, "guid", f"{ATOM}id")) or url

    return RawDocument(
        external_id=identifier,
        url=url,
        title=normalise_text(title),
        abstract=strip_html(summary),
        published_at=published,
        authors=_authors(item),
        canonical_ids={},
    )


def parse_feed(xml_text: str) -> list[RawDocument]:
    """Parse an RSS or Atom document into RawDocuments.

    defusedxml because a feed is third-party input and a stock XML parser is
    vulnerable to entity expansion (docs/07, "malicious content").
    """
    root = DefusedET.fromstring(xml_text)
    items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    documents: list[RawDocument] = []
    for item in items:
        document = parse_entry(item)
        if document is not None:
            documents.append(document)
    return documents


class RssFetcher:
    """Reads one RSS or Atom feed.

    Feeds have no date window and no paging: a fetch returns whatever is
    currently in the file, typically the last ten to fifty entries. Filtering to
    the requested window therefore happens here rather than in a query
    parameter, and a source that publishes more often than the job runs will
    drop entries off the end of its own feed. That is a real limitation of
    feed-based sources, recorded rather than hidden.
    """

    def __init__(self, client: SafeHttpClient, *, url: str) -> None:
        self._client = client
        self._url = url

    def discover(self, since: datetime) -> Iterator[RawDocument]:
        response = self._client.get(self._url)
        documents = parse_feed(response.text)
        log.info("feed_fetched", url=self._url, entries=len(documents))

        undated = 0
        for document in documents:
            if document.published_at is None:
                # Keep it: a feed entry with no date is usually a publisher's
                # omission, not an old document, and dropping it silently loses
                # real announcements. Triage sees it with published_at NULL.
                undated += 1
                yield document
            elif document.published_at >= since:
                yield document

        if undated:
            log.warning("feed_entries_without_dates", url=self._url, count=undated)
