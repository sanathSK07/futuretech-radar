"""arXiv Atom parsing and paging.

The fixtures follow the response format documented at
https://info.arxiv.org/help/api/user-manual.html. They are the contract this
parser is written against; a live smoke test on a developer machine confirms the
real feed still matches (see `make smoke-arxiv`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from radar.pipeline.fetchers.arxiv import (
    ArxivFetcher,
    parse_atom_datetime,
    parse_feed,
    split_arxiv_id,
)
from radar.pipeline.http import SafeHttpClient

FIXTURES = Path(__file__).parent / "fixtures"

# Every test here talks to a mock transport, so no real DNS is wanted.


@pytest.fixture(autouse=True)
def _no_real_dns(public_dns: None) -> None:
    """Route hostname resolution through the hermetic fixture."""


@pytest.fixture
def feed_xml() -> str:
    return (FIXTURES / "arxiv_cs_ro.xml").read_text(encoding="utf-8")


@pytest.fixture
def empty_feed_xml() -> str:
    return (FIXTURES / "arxiv_empty.xml").read_text(encoding="utf-8")


class TestSplitArxivId:
    @pytest.mark.parametrize(
        ("entry_id", "expected"),
        [
            ("http://arxiv.org/abs/2609.01234v2", ("2609.01234", "v2")),
            ("https://arxiv.org/abs/2609.01234v11", ("2609.01234", "v11")),
            ("http://arxiv.org/abs/2609.01234", ("2609.01234", None)),
            ("http://arxiv.org/abs/hep-ex/0307015v1", ("hep-ex/0307015", "v1")),
        ],
    )
    def test_it_separates_the_version(
        self, entry_id: str, expected: tuple[str, str | None]
    ) -> None:
        assert split_arxiv_id(entry_id) == expected

    def test_the_versionless_id_is_what_identifies_a_paper(self) -> None:
        """v1 and v2 of one paper must resolve to the same external_id.

        Otherwise a revision would be ingested as a second, separate document.
        """
        v1, _ = split_arxiv_id("http://arxiv.org/abs/2609.01234v1")
        v2, _ = split_arxiv_id("http://arxiv.org/abs/2609.01234v2")
        assert v1 == v2


class TestParseAtomDatetime:
    def test_it_converts_to_utc(self) -> None:
        parsed = parse_atom_datetime("2026-09-16T14:02:11-04:00")
        assert parsed == datetime(2026, 9, 16, 18, 2, 11, tzinfo=UTC)

    def test_a_naive_timestamp_is_assumed_utc(self) -> None:
        parsed = parse_atom_datetime("2026-09-16T14:02:11")
        assert parsed is not None
        assert parsed.tzinfo is UTC

    def test_rubbish_returns_none_rather_than_raising(self) -> None:
        assert parse_atom_datetime("not a date") is None


class TestParseFeed:
    def test_it_reports_the_total_and_parses_every_entry(self, feed_xml: str) -> None:
        documents, total = parse_feed(feed_xml)
        assert total == 4213
        assert len(documents) == 3

    def test_it_extracts_the_first_entry_faithfully(self, feed_xml: str) -> None:
        documents, _ = parse_feed(feed_xml)
        first = documents[0]
        assert first.external_id == "2609.01234"
        assert first.url == "https://arxiv.org/abs/2609.01234"
        assert first.published_at == datetime(2026, 9, 16, 18, 2, 11, tzinfo=UTC)
        assert first.abstract is not None
        assert "78% success rate" in first.abstract

    def test_a_wrapped_title_is_collapsed_to_one_line(self, feed_xml: str) -> None:
        documents, _ = parse_feed(feed_xml)
        assert documents[0].title == (
            "Dexterous In-Hand Manipulation from Monocular Human Demonstration"
        )

    def test_authors_and_affiliations_are_kept(self, feed_xml: str) -> None:
        documents, _ = parse_feed(feed_xml)
        assert documents[0].authors == [
            {"name": "A. Researcher", "affiliation": "ETH Zurich"},
            {"name": "B. Coauthor"},
        ]

    def test_identifiers_and_categories_are_captured(self, feed_xml: str) -> None:
        documents, _ = parse_feed(feed_xml)
        ids = documents[0].canonical_ids
        assert ids["arxiv"] == "2609.01234"
        assert ids["arxiv_version"] == "v2"
        assert ids["doi"] == "10.1109/TRO.2026.1234567"
        assert ids["arxiv_categories"] == "cs.RO,cs.LG"
        assert ids["arxiv_primary_category"] == "cs.RO"

    def test_an_entry_without_a_doi_simply_omits_it(self, feed_xml: str) -> None:
        documents, _ = parse_feed(feed_xml)
        assert "doi" not in documents[1].canonical_ids

    def test_the_licence_note_records_that_eprints_are_not_redistributed(
        self, feed_xml: str
    ) -> None:
        documents, _ = parse_feed(feed_xml)
        assert documents[0].licence is not None
        assert "CC0" in documents[0].licence

    def test_an_empty_feed_parses_to_nothing(self, empty_feed_xml: str) -> None:
        documents, total = parse_feed(empty_feed_xml)
        assert documents == []
        assert total == 0

    def test_the_same_content_hashes_identically_regardless_of_whitespace(
        self, feed_xml: str
    ) -> None:
        documents, _ = parse_feed(feed_xml)
        original = documents[0]
        assert original.content_hash == original.content_hash
        assert len(original.content_hash) == 64


class TestArxivFetcher:
    def _client(self, responses: list[str]) -> SafeHttpClient:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            index = min(calls["n"], len(responses) - 1)
            calls["n"] += 1
            return httpx.Response(200, text=responses[index])

        return SafeHttpClient(
            contact="test@example.org",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    def test_the_query_url_is_built_correctly(self) -> None:
        client = self._client(["<feed/>"])
        fetcher = ArxivFetcher(client, category="cs.RO", page_size=50)
        parsed = urlsplit(fetcher.build_url(start=100))
        query = parse_qs(parsed.query)
        assert parsed.hostname == "export.arxiv.org"
        assert query["search_query"] == ["cat:cs.RO"]
        assert query["start"] == ["100"]
        assert query["max_results"] == ["50"]
        assert query["sortBy"] == ["submittedDate"]
        assert query["sortOrder"] == ["descending"]

    def test_a_category_is_required(self) -> None:
        client = self._client(["<feed/>"])
        with pytest.raises(ValueError, match="category is required"):
            ArxivFetcher(client, category="")

    def test_it_stops_at_the_publication_window(self, feed_xml: str) -> None:
        """Results are newest first, so the first old entry ends the scan."""
        fetcher = ArxivFetcher(self._client([feed_xml]), category="cs.RO")
        since = datetime(2026, 9, 10, tzinfo=UTC)
        found = list(fetcher.discover(since))
        # The third fixture entry is from August and must be excluded.
        assert [d.external_id for d in found] == ["2609.01234", "2609.01111"]

    def test_a_wide_window_keeps_everything_on_the_page(self, feed_xml: str) -> None:
        fetcher = ArxivFetcher(self._client([feed_xml]), category="cs.RO", page_size=3)
        found = list(fetcher.discover(datetime(2020, 1, 1, tzinfo=UTC)))
        assert len(found) == 3

    def test_an_empty_first_page_yields_nothing(self, empty_feed_xml: str) -> None:
        fetcher = ArxivFetcher(self._client([empty_feed_xml]), category="cs.RO")
        assert list(fetcher.discover(datetime(2020, 1, 1, tzinfo=UTC))) == []

    def test_a_repeated_id_across_pages_is_yielded_once(self, feed_xml: str) -> None:
        """Paging a live feed can overlap when new papers arrive mid-scan."""
        fetcher = ArxivFetcher(self._client([feed_xml, feed_xml]), category="cs.RO", page_size=3)
        found = list(fetcher.discover(datetime(2020, 1, 1, tzinfo=UTC)))
        assert len(found) == len({d.external_id for d in found})
