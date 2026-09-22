"""arXiv harvester, over OAI-PMH.

Why this exists alongside ``arxiv.py``
--------------------------------------
The Atom search API at ``export.arxiv.org/api/query`` sits behind an edge cache
that serves what it has stored and answers ``406`` to anything that would need
an origin fetch. Read from the response headers on 2026-09-21: a ``200`` carried
``age: 178`` and ``x-cache: MISS, HIT, HIT``; the ``406`` alongside it carried
``x-cache: MISS, MISS`` and ``cache-control: private, no-store``. Confirmed by
varying one parameter at a time — ``start=100`` refused 0/8 while ``start=0``
returned 8/8, and ``max_results=99`` refused 0/8 while ``max_results=100``
returned 8/8. Any URL the cache has not already stored is refused, whatever it
asks for.

That makes the search API unusable as a harvest transport: a daily job needs to
ask a question nobody asked yesterday. ``export.arxiv.org/oai2`` is arXiv's
documented bulk interface (https://info.arxiv.org/help/oa/index.html) and does
not behave that way — four cold ``ListRecords`` URLs returned ``200`` four times
out of four. So metadata harvesting moved here, and the Atom fetcher stays only
as a smoke-test path.

What the window means
---------------------
OAI's ``from`` filters on a record's *datestamp*, which arXiv sets when the
record is created **or revised**. That is a superset of "submitted in this
window", and deliberately kept: a paper revised yesterday is a discovery too. It
costs nothing, because ``external_id`` is the versionless arXiv id and insertion
is ``ON CONFLICT DO NOTHING`` — a revision of a paper already stored writes
nothing, and a revision of one never seen is stored once.

The arXiv metadata format carries no version number, so unlike the Atom fetcher
this one records no ``arxiv_version``. ``<updated>`` is kept instead, which says
a revision happened without claiming which one.

Only metadata is taken. arXiv metadata is CC0; the e-prints themselves are not
redistributable, so this fetcher never downloads or stores PDFs or source.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from urllib.parse import urlencode
from xml.etree.ElementTree import Element

import structlog
from defusedxml import ElementTree as DefusedET

from radar.pipeline.fetchers.base import RawDocument, normalise_text
from radar.pipeline.http import SafeHttpClient

log = structlog.get_logger(__name__)

ARXIV_OAI_URL = "https://export.arxiv.org/oai2"
"""Verified live on 2026-09-21. ``oaipmh.arxiv.org``, named in some third-party
guides, answers 404; this is the host arXiv's own documentation gives."""

OAI = "{http://www.openarchives.org/OAI/2.0/}"
ARXIV_META = "{http://arxiv.org/OAI/arXiv/}"

METADATA_PREFIX = "arXiv"

MAX_PAGES = 60
"""A ceiling on resumption-token following.

arXiv pages ``ListRecords`` at 1,000 records, so this is 60,000 records in one
source's window. Reaching it is logged rather than passed over: the window was
not fully harvested, and the next run's ``since`` must not assume otherwise.
"""

_BENIGN_ERROR_CODES = frozenset({"noRecordsMatch"})
"""An empty result is an answer, not a failure: most days a narrow category has
nothing new, and a source that reported that as an error would cry wolf nightly."""


class OaiError(RuntimeError):
    """The server returned an OAI-PMH ``<error>`` element.

    Carries the protocol error code so a caller can tell ``badArgument`` (our
    bug) from ``badResumptionToken`` (an expired harvest) without string
    matching on the message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def parse_oai_date(value: str | None) -> datetime | None:
    """Parse arXiv's ``YYYY-MM-DD`` metadata date into an aware UTC datetime.

    The record carries a date, not a timestamp, so this is midnight UTC on that
    day — precise enough for a daily job, and honest about what arXiv said.
    """
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        log.warning("unparseable_oai_date", value=value)
        return None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _text(element: Element, path: str) -> str | None:
    found = element.find(path)
    if found is None or found.text is None:
        return None
    stripped = found.text.strip()
    return stripped or None


def parse_authors(metadata: Element) -> list[dict[str, str]]:
    """Read the ``<authors>`` block into name records.

    arXiv supplies surname and forenames separately. Both are kept alongside the
    joined display name, because splitting a name correctly is hard and arXiv
    has already done it — throwing that away would mean guessing it back later
    during entity resolution.
    """
    authors: list[dict[str, str]] = []
    for author in metadata.findall(f"{ARXIV_META}authors/{ARXIV_META}author"):
        keyname = _text(author, f"{ARXIV_META}keyname")
        forenames = _text(author, f"{ARXIV_META}forenames")
        suffix = _text(author, f"{ARXIV_META}suffix")
        parts = [part for part in (forenames, keyname, suffix) if part]
        if not parts:
            continue
        record = {"name": " ".join(parts)}
        if keyname:
            record["keyname"] = keyname
        if forenames:
            record["forenames"] = forenames
        affiliation = _text(author, f"{ARXIV_META}affiliation")
        if affiliation:
            record["affiliation"] = affiliation
        authors.append(record)
    return authors


def parse_record(record: Element) -> RawDocument | None:
    """Turn one ``<record>`` into a document, or None if it carries none.

    Returns None for a tombstone (``<header status="deleted">``) and for a
    record whose metadata is missing an id or a title. A deleted record is not a
    failure: arXiv withdraws papers, and the protocol announces that by sending
    a header with no metadata.
    """
    header = record.find(f"{OAI}header")
    if header is None:
        log.warning("oai_record_without_header")
        return None
    if header.get("status") == "deleted":
        log.info("oai_record_deleted", identifier=_text(header, f"{OAI}identifier"))
        return None

    metadata = record.find(f"{OAI}metadata/{ARXIV_META}arXiv")
    if metadata is None:
        log.warning("oai_record_without_metadata", identifier=_text(header, f"{OAI}identifier"))
        return None

    arxiv_id = _text(metadata, f"{ARXIV_META}id")
    title = _text(metadata, f"{ARXIV_META}title")
    if not arxiv_id or not title:
        log.warning("oai_record_missing_id_or_title", arxiv_id=arxiv_id)
        return None

    canonical_ids: dict[str, str] = {"arxiv": arxiv_id}

    doi = _text(metadata, f"{ARXIV_META}doi")
    if doi:
        canonical_ids["doi"] = doi

    # arXiv gives categories space-separated in one element; the Atom fetcher
    # stores them comma-joined, and the two must agree or the same paper reads
    # differently depending on which transport found it.
    categories = (_text(metadata, f"{ARXIV_META}categories") or "").split()
    if categories:
        canonical_ids["arxiv_categories"] = ",".join(categories)
        canonical_ids["arxiv_primary_category"] = categories[0]

    updated = _text(metadata, f"{ARXIV_META}updated")
    if updated:
        canonical_ids["arxiv_updated"] = updated

    licence_url = _text(metadata, f"{ARXIV_META}license")
    licence = (
        f"arXiv metadata CC0; e-print licensed {licence_url}, not redistributed"
        if licence_url
        else "arXiv metadata CC0; e-print under its own licence, not redistributed"
    )

    abstract = _text(metadata, f"{ARXIV_META}abstract")

    return RawDocument(
        external_id=arxiv_id,
        url=f"https://arxiv.org/abs/{arxiv_id}",
        title=normalise_text(title),
        abstract=normalise_text(abstract) if abstract else None,
        published_at=parse_oai_date(_text(metadata, f"{ARXIV_META}created")),
        authors=parse_authors(metadata),
        canonical_ids=canonical_ids,
        licence=licence,
    )


def parse_page(xml_text: str) -> tuple[list[RawDocument], str | None]:
    """Parse one ``ListRecords`` response into documents and a resumption token.

    The token is None when the harvest is complete — either the element is
    absent or, as the protocol requires on the final page, present but empty.

    Uses defusedxml, because the response is third-party input and a stock XML
    parser is vulnerable to entity-expansion attacks (docs/07, "malicious
    content").
    """
    root: Element = DefusedET.fromstring(xml_text)

    error = root.find(f"{OAI}error")
    if error is not None:
        code = error.get("code") or "unknown"
        message = (error.text or "").strip()
        if code in _BENIGN_ERROR_CODES:
            log.info("oai_no_records", code=code, message=message)
            return [], None
        raise OaiError(code, message)

    listing = root.find(f"{OAI}ListRecords")
    if listing is None:
        raise OaiError("malformedResponse", "the response carried no ListRecords element")

    documents = [
        document
        for record in listing.findall(f"{OAI}record")
        if (document := parse_record(record)) is not None
    ]

    token_element = listing.find(f"{OAI}resumptionToken")
    token = (token_element.text or "").strip() if token_element is not None else ""
    return documents, token or None


class ArxivOaiFetcher:
    """Harvests one arXiv OAI set.

    ``set_spec`` is a setSpec as ``ListSets`` reports it, e.g. ``cs:cs:RO`` or
    ``physics:quant-ph``. Passing None harvests the whole archive, which is far
    too much for this project and is only here because the protocol allows it.
    """

    def __init__(
        self, client: SafeHttpClient, *, set_spec: str | None = None, max_pages: int = MAX_PAGES
    ) -> None:
        self._client = client
        self._set_spec = set_spec or None
        self._max_pages = max_pages

    def build_url(self, *, since: datetime) -> str:
        """The first request of a harvest.

        arXiv's OAI granularity is a day, so ``since`` is floored to its UTC
        date. Asking for a finer timestamp is a ``badArgument``.
        """
        params: dict[str, str] = {
            "verb": "ListRecords",
            "metadataPrefix": METADATA_PREFIX,
            "from": since.astimezone(UTC).date().isoformat(),
        }
        if self._set_spec:
            params["set"] = self._set_spec
        return f"{ARXIV_OAI_URL}?{urlencode(params)}"

    def resume_url(self, token: str) -> str:
        """A continuation request.

        The protocol is explicit that a resumption request carries the verb and
        the token and nothing else: repeating ``set`` or ``from`` alongside it is
        a ``badArgument``.
        """
        return f"{ARXIV_OAI_URL}?{urlencode({'verb': 'ListRecords', 'resumptionToken': token})}"

    def discover(self, since: datetime) -> Iterator[RawDocument]:
        """Yield every record whose datestamp falls at or after ``since``."""
        url = self.build_url(since=since)
        seen_tokens: set[str] = set()
        harvested = 0

        for page in range(self._max_pages):
            documents, token = parse_page(self._client.get(url).text)
            harvested += len(documents)
            log.info(
                "oai_page",
                set_spec=self._set_spec,
                page=page,
                records=len(documents),
                harvested=harvested,
                has_token=bool(token),
            )

            yield from documents

            if token is None:
                return
            if token in seen_tokens:
                # A server that hands back a token it already gave would loop
                # forever. Stop and say so rather than harvesting until the
                # page ceiling hides it.
                log.warning("oai_token_repeated", set_spec=self._set_spec, harvested=harvested)
                return
            seen_tokens.add(token)
            url = self.resume_url(token)

        log.warning(
            "oai_page_limit_reached",
            set_spec=self._set_spec,
            pages=self._max_pages,
            harvested=harvested,
            note="the window was not fully harvested; narrow the --since window",
        )
