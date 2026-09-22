"""The bioRxiv fetcher: the biotech half of the corpus."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from radar.pipeline.fetchers.biorxiv import (
    BiorxivFetcher,
    parse_authors,
    parse_biorxiv_date,
    parse_record,
    parse_response,
)
from radar.pipeline.http import InvalidJsonError, SafeHttpClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_real_dns(public_dns: None) -> None:
    """Route hostname resolution through the hermetic fixture."""


@pytest.fixture
def page() -> dict[str, object]:
    return json.loads((FIXTURES / "biorxiv_page.json").read_text(encoding="utf-8"))


def client_for(body: str, *, content_type: str = "application/json") -> SafeHttpClient:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": content_type})
    )
    return SafeHttpClient(
        contact="a@b.org", client=httpx.Client(transport=transport), max_attempts=1
    )


class TestParsing:
    def test_a_record_becomes_a_document(self, page: dict[str, object]) -> None:
        record = page["collection"][0]  # type: ignore[index]
        document = parse_record(record)
        assert document is not None
        assert document.external_id == "10.1101/2026.09.14.612345"
        assert document.canonical_ids == {"doi": "10.1101/2026.09.14.612345"}
        assert document.published_at == datetime(2026, 9, 14, tzinfo=UTC)
        assert document.licence == "cc_by"
        assert "1 in 340 kb" in str(document.abstract)

    def test_the_external_id_is_the_unversioned_doi(self, page: dict[str, object]) -> None:
        """bioRxiv keeps the DOI across versions, so a revision updates one record."""
        record = dict(page["collection"][1])  # type: ignore[index, arg-type]
        assert parse_record(record).external_id == record["doi"]  # type: ignore[union-attr]

    def test_the_url_points_at_the_version_that_was_read(self, page: dict[str, object]) -> None:
        record = page["collection"][1]  # type: ignore[index]
        document = parse_record(record)
        assert document is not None
        assert document.url.endswith("v2")

    def test_a_record_without_a_doi_is_dropped(self, page: dict[str, object]) -> None:
        assert parse_record(page["collection"][2]) is None  # type: ignore[index]

    def test_authors_are_split_but_not_reformatted(self) -> None:
        """Rewriting a name invents information about a person."""
        assert parse_authors("Okonkwo, A.; Patel, R.; Lindqvist, S.") == [
            {"name": "Okonkwo, A."},
            {"name": "Patel, R."},
            {"name": "Lindqvist, S."},
        ]

    def test_no_authors_is_an_empty_list(self) -> None:
        assert parse_authors("") == []
        assert parse_authors(None) == []

    def test_a_bad_date_is_none_not_an_exception(self) -> None:
        assert parse_biorxiv_date("not a date") is None
        assert parse_biorxiv_date(None) is None

    def test_the_total_is_read_from_the_messages_block(self, page: dict[str, object]) -> None:
        documents, total = parse_response(page)  # type: ignore[arg-type]
        assert total == 3
        assert len(documents) == 2  # the record with no DOI is dropped


class TestDiscovery:
    def test_a_category_filter_keeps_only_that_category(self) -> None:
        """The API has no category parameter, so this happens client-side."""
        body = (FIXTURES / "biorxiv_page.json").read_text(encoding="utf-8")
        with client_for(body) as client:
            fetcher = BiorxivFetcher(client, category="synthetic biology")
            titles = [d.title for d in fetcher.discover(datetime(2026, 9, 1, tzinfo=UTC))]
        assert titles == ["Cell-free synthesis of a 1.2 Mb bacterial genome"]

    def test_without_a_filter_every_usable_record_is_returned(self) -> None:
        body = (FIXTURES / "biorxiv_page.json").read_text(encoding="utf-8")
        with client_for(body) as client:
            fetcher = BiorxivFetcher(client)
            assert len(list(fetcher.discover(datetime(2026, 9, 1, tzinfo=UTC)))) == 2

    def test_the_category_match_is_case_insensitive(self) -> None:
        body = (FIXTURES / "biorxiv_page.json").read_text(encoding="utf-8")
        with client_for(body) as client:
            fetcher = BiorxivFetcher(client, category="Synthetic Biology")
            assert len(list(fetcher.discover(datetime(2026, 9, 1, tzinfo=UTC)))) == 1

    def test_the_window_is_in_the_url(self) -> None:
        """The API takes a date interval; getting it wrong silently fetches nothing."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, text='{"messages":[{"total":0}],"collection":[]}')

        transport = httpx.MockTransport(handler)
        with SafeHttpClient(
            contact="a@b.org", client=httpx.Client(transport=transport), max_attempts=1
        ) as client:
            fetcher = BiorxivFetcher(client, server="medrxiv")
            list(fetcher.discover(datetime(2026, 9, 1, tzinfo=UTC)))

        assert "/details/medrxiv/2026-09-01/" in seen[0]
        assert seen[0].endswith("/0")

    def test_a_single_short_page_stops_paging(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, text='{"messages":[{"total":1}],"collection":[]}')

        transport = httpx.MockTransport(handler)
        with SafeHttpClient(
            contact="a@b.org", client=httpx.Client(transport=transport), max_attempts=1
        ) as client:
            list(BiorxivFetcher(client).discover(datetime(2026, 9, 1, tzinfo=UTC)))
        assert calls == 1

    def test_an_html_error_page_names_the_source(self) -> None:
        """A decode error three frames away from the URL is unactionable."""
        with client_for("<html>502 Bad Gateway</html>", content_type="text/html") as client:
            fetcher = BiorxivFetcher(client)
            with pytest.raises(InvalidJsonError, match="did not return JSON"):
                list(fetcher.discover(datetime(2026, 9, 1, tzinfo=UTC)))


class TestPaging:
    """The live API's page size is not the documented one."""

    def test_a_short_page_does_not_end_the_walk(self) -> None:
        """The bug the first live run hid: 30 returned, 164 total, 134 lost.

        A page shorter than the documented size is indistinguishable from a
        finished window unless the server's own total is checked, so the walk
        ends on an empty page or on reaching that total — never on a guess
        about page size.
        """
        pages = [
            {
                "messages": [{"total": 5}],
                "collection": [
                    {
                        "doi": f"10.1101/2026.09.14.{index:06d}",
                        "title": f"Preprint {index}",
                        "date": "2026-09-14",
                        "category": "synthetic biology",
                        "abstract": "An abstract.",
                    }
                    for index in range(2)
                ],
            },
            {
                "messages": [{"total": 5}],
                "collection": [
                    {
                        "doi": f"10.1101/2026.09.15.{index:06d}",
                        "title": f"Preprint {index}",
                        "date": "2026-09-15",
                        "category": "synthetic biology",
                        "abstract": "An abstract.",
                    }
                    for index in range(3)
                ],
            },
        ]
        cursors: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cursors.append(str(request.url).rsplit("/", 1)[-1])
            page = pages[len(cursors) - 1] if len(cursors) <= len(pages) else {"collection": []}
            return httpx.Response(200, text=json.dumps(page))

        transport = httpx.MockTransport(handler)
        with SafeHttpClient(
            contact="a@b.org", client=httpx.Client(transport=transport), max_attempts=1
        ) as client:
            found = list(BiorxivFetcher(client).discover(datetime(2026, 9, 1, tzinfo=UTC)))

        assert len(found) == 5
        assert cursors == ["0", "2"], "the cursor must advance by what was returned"

    def test_an_empty_page_ends_the_walk(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, text='{"messages":[{"total":9999}],"collection":[]}')

        transport = httpx.MockTransport(handler)
        with SafeHttpClient(
            contact="a@b.org", client=httpx.Client(transport=transport), max_attempts=1
        ) as client:
            assert list(BiorxivFetcher(client).discover(datetime(2026, 9, 1, tzinfo=UTC))) == []
        assert calls == 1, "an inflated total must not cause an endless walk"
