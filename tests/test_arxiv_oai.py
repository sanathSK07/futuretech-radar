"""The arXiv OAI-PMH harvester.

The Atom search API cannot serve a daily harvest — its edge cache refuses any
URL it has not already stored — so this is the transport bulk arXiv metadata
actually arrives over. These tests pin the two things that broke elsewhere:
paging that stops early and loses records, and a URL shape that quietly changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from defusedxml import ElementTree as DefusedET

from radar.pipeline.fetchers.arxiv_oai import (
    ARXIV_OAI_URL,
    ArxivOaiFetcher,
    OaiError,
    parse_authors,
    parse_oai_date,
    parse_page,
)
from radar.pipeline.http import SafeHttpClient

FIXTURES = Path(__file__).parent / "fixtures"
SINCE = datetime(2026, 9, 21, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_real_dns(public_dns: None) -> None:
    """Route hostname resolution through the hermetic fixture."""


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def client_for(*bodies: str) -> tuple[SafeHttpClient, list[str]]:
    """A client that answers each request with the next body, and records URLs."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        index = min(len(seen) - 1, len(bodies) - 1)
        return httpx.Response(200, text=bodies[index], headers={"content-type": "text/xml"})

    client = SafeHttpClient(
        contact="a@b.org",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=1,
    )
    return client, seen


class TestParsing:
    def test_a_record_becomes_a_document(self) -> None:
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        first = documents[0]
        assert first.external_id == "2609.20822"
        assert first.url == "https://arxiv.org/abs/2609.20822"
        assert first.title.startswith("Dexterous In-Hand Manipulation")
        assert first.published_at == datetime(2026, 9, 21, tzinfo=UTC)
        assert "74% success rate" in str(first.abstract)

    def test_the_external_id_carries_no_version(self) -> None:
        """It must collide with the Atom fetcher's ids, or a revision stores twice.

        The arXiv metadata format has no version element at all, so this is a
        property of the format rather than something the parser strips — pinned
        here so a future switch to a format that does carry one is noticed.
        """
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert all("v" not in d.external_id for d in documents)
        assert all("arxiv_version" not in d.canonical_ids for d in documents)

    def test_a_wrapped_title_is_one_line(self) -> None:
        """arXiv hard-wraps titles; a stored newline would corrupt every display."""
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert documents[1].title == "A Second Paper With A Wrapped Title"

    def test_categories_are_comma_joined_like_the_atom_fetcher(self) -> None:
        """OAI gives them space-separated. The two transports must agree."""
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert documents[0].canonical_ids["arxiv_categories"] == "cs.RO,cs.LG"
        assert documents[0].canonical_ids["arxiv_primary_category"] == "cs.RO"

    def test_a_doi_is_kept_when_given(self) -> None:
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert documents[0].canonical_ids["doi"] == "10.1000/example.2609.20822"
        assert "doi" not in documents[1].canonical_ids

    def test_a_revision_date_is_recorded_without_claiming_a_version(self) -> None:
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert documents[1].canonical_ids["arxiv_updated"] == "2026-09-21"
        assert "arxiv_updated" not in documents[0].canonical_ids

    def test_the_licence_names_the_eprint_terms_when_arxiv_gives_them(self) -> None:
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert "creativecommons.org/licenses/by/4.0" in str(documents[0].licence)
        assert "CC0" in str(documents[0].licence)
        # No <license> element: the metadata is still CC0, the e-print unstated.
        assert documents[1].licence == (
            "arXiv metadata CC0; e-print under its own licence, not redistributed"
        )

    def test_a_deleted_record_is_skipped_not_stored(self) -> None:
        """arXiv withdraws papers; the protocol says so with a bare header."""
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert [d.external_id for d in documents] == ["2609.20822", "2609.20823"]

    def test_the_content_hash_matches_the_atom_fetchers(self) -> None:
        """Same paper, two transports, one duplicate-detection fingerprint."""
        from radar.pipeline.fetchers.base import content_hash

        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        raw_abstract = (
            "  We present a system that learns in-hand reorientation from single-camera\n"
            "  video of human hands. On a 16-DoF hand the policy achieved a 74% success rate\n"
            "  across 12 objects.\n"
        )
        assert documents[0].content_hash == content_hash(
            "Dexterous In-Hand Manipulation from Monocular Human Demonstration", raw_abstract
        )


class TestAuthors:
    def test_forenames_and_surname_are_both_kept(self) -> None:
        """arXiv has already split the name; guessing it back later would be worse."""
        documents, _ = parse_page(fixture_text("arxiv_oai_cs_ro.xml"))
        assert documents[0].authors[0] == {
            "name": "Adaeze Okonkwo",
            "keyname": "Okonkwo",
            "forenames": "Adaeze",
        }

    def test_an_author_with_only_a_surname_is_kept(self) -> None:
        """Collaborations are filed under one keyname with no forenames."""
        xml = (
            '<arXiv xmlns="http://arxiv.org/OAI/arXiv/"><authors>'
            "<author><keyname>LIGO Scientific Collaboration</keyname></author>"
            "</authors></arXiv>"
        )
        assert parse_authors(DefusedET.fromstring(xml)) == [
            {"name": "LIGO Scientific Collaboration", "keyname": "LIGO Scientific Collaboration"}
        ]

    def test_an_empty_author_element_is_dropped_not_named_blank(self) -> None:
        xml = (
            '<arXiv xmlns="http://arxiv.org/OAI/arXiv/"><authors>'
            "<author></author></authors></arXiv>"
        )
        assert parse_authors(DefusedET.fromstring(xml)) == []


class TestDates:
    def test_a_date_becomes_midnight_utc(self) -> None:
        assert parse_oai_date("2026-09-21") == datetime(2026, 9, 21, tzinfo=UTC)

    def test_a_bad_date_is_none_not_an_exception(self) -> None:
        assert parse_oai_date("not a date") is None
        assert parse_oai_date(None) is None


class TestErrors:
    def test_no_records_is_an_empty_result_not_a_failure(self) -> None:
        """Most days a narrow category has nothing new. That is not an outage."""
        documents, token = parse_page(fixture_text("arxiv_oai_error.xml"))
        assert documents == []
        assert token is None

    def test_a_real_protocol_error_is_raised_with_its_code(self) -> None:
        xml = (
            '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
            '<error code="badArgument">unknown set</error></OAI-PMH>'
        )
        with pytest.raises(OaiError) as caught:
            parse_page(xml)
        assert caught.value.code == "badArgument"

    def test_a_response_without_a_listing_is_an_error_not_silence(self) -> None:
        """Returning zero documents here would look exactly like a quiet day."""
        xml = '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"></OAI-PMH>'
        with pytest.raises(OaiError, match="ListRecords"):
            parse_page(xml)


class TestUrls:
    def test_the_first_request_carries_the_set_and_the_window(self) -> None:
        client, seen = client_for(fixture_text("arxiv_oai_error.xml"))
        with client:
            list(ArxivOaiFetcher(client, set_spec="cs:cs:RO").discover(SINCE))
        assert seen[0].startswith(ARXIV_OAI_URL)
        assert "verb=ListRecords" in seen[0]
        assert "metadataPrefix=arXiv" in seen[0]
        assert "from=2026-09-21" in seen[0]
        assert "set=cs%3Acs%3ARO" in seen[0]

    def test_the_endpoint_is_the_one_arxiv_redirects_to(self) -> None:
        """Pin the post-redirect host, because the hop is not free.

        The rate limiter runs before every redirect hop, so pointing at
        export.arxiv.org/oai2 spends a three-second wait on each of eleven
        sources to be told where to go. Observed 301 -> this URL on every source
        in the first live harvest, 2026-09-24.
        """
        assert ARXIV_OAI_URL == "https://oaipmh.arxiv.org/oai"

    def test_the_window_is_floored_to_a_day(self) -> None:
        """OAI's granularity is a date; a timestamp is a badArgument."""
        client, seen = client_for(fixture_text("arxiv_oai_error.xml"))
        with client:
            fetcher = ArxivOaiFetcher(client, set_spec="cs:cs:RO")
            list(fetcher.discover(datetime(2026, 9, 21, 14, 30, tzinfo=UTC)))
        assert "from=2026-09-21" in seen[0]
        assert "14" not in seen[0].split("from=")[1]

    def test_a_resumption_request_carries_the_token_and_nothing_else(self) -> None:
        """Repeating set or from alongside a token is a protocol error."""
        client, seen = client_for(
            fixture_text("arxiv_oai_cs_ro.xml"), fixture_text("arxiv_oai_page2.xml")
        )
        with client:
            list(ArxivOaiFetcher(client, set_spec="cs:cs:RO").discover(SINCE))
        assert "resumptionToken=3939516%7C1001" in seen[1]
        assert "set=" not in seen[1]
        assert "from=" not in seen[1]
        assert "metadataPrefix" not in seen[1]


class TestPaging:
    def test_the_second_page_is_harvested(self) -> None:
        """The failure this replaces lost 82% of a source without a word."""
        client, _ = client_for(
            fixture_text("arxiv_oai_cs_ro.xml"), fixture_text("arxiv_oai_page2.xml")
        )
        with client:
            fetcher = ArxivOaiFetcher(client, set_spec="cs:cs:RO")
            ids = [document.external_id for document in fetcher.discover(SINCE)]
        assert ids == ["2609.20822", "2609.20823", "2609.20900"]

    def test_an_empty_token_ends_the_harvest(self) -> None:
        """The protocol's way of saying 'that was the last page'."""
        client, seen = client_for(
            fixture_text("arxiv_oai_cs_ro.xml"), fixture_text("arxiv_oai_page2.xml")
        )
        with client:
            list(ArxivOaiFetcher(client, set_spec="cs:cs:RO").discover(SINCE))
        assert len(seen) == 2

    def test_a_repeated_token_stops_rather_than_looping(self) -> None:
        """A server that re-issues a token would otherwise spin to the page cap."""
        client, seen = client_for(fixture_text("arxiv_oai_cs_ro.xml"))
        with client:
            list(ArxivOaiFetcher(client, set_spec="cs:cs:RO").discover(SINCE))
        assert len(seen) == 2

    def test_the_page_ceiling_is_honoured(self) -> None:
        pages = [
            '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>'
            f"<resumptionToken>token-{index}</resumptionToken>"
            "</ListRecords></OAI-PMH>"
            for index in range(10)
        ]
        client, seen = client_for(*pages)
        with client:
            fetcher = ArxivOaiFetcher(client, set_spec="cs:cs:RO", max_pages=3)
            list(fetcher.discover(SINCE))
        assert len(seen) == 3
