"""The RSS and Atom fetcher.

These feeds are where the evidence arXiv cannot supply comes from: lab
announcements, regulatory decisions, company deployments. The tests are written
against fixtures in both dialects, because official feeds are split roughly
evenly between them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from radar.pipeline.fetchers.rss import (
    MAX_SUMMARY_CHARACTERS,
    RssFetcher,
    parse_feed,
    parse_feed_datetime,
    strip_html,
)
from radar.pipeline.http import SafeHttpClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_real_dns(public_dns: None) -> None:
    """Route hostname resolution through the hermetic fixture."""


def client_for(body: str, *, content_type: str = "application/rss+xml") -> SafeHttpClient:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": content_type})
    )
    return SafeHttpClient(
        contact="a@b.org", client=httpx.Client(transport=transport), max_attempts=1
    )


class TestHtmlStripping:
    def test_tags_are_removed_and_words_kept(self) -> None:
        assert strip_html("<p>Sustained for <strong>12 minutes</strong>.</p>") == (
            "Sustained for 12 minutes."
        )

    def test_entities_are_resolved(self) -> None:
        assert strip_html("20&nbsp;T &amp; rising") == "20 T & rising"

    def test_a_comparison_is_not_eaten(self) -> None:
        """A regex stripper treats 'a < b' as an unterminated tag and loses the rest."""
        assert "1 in 340 kb" in str(strip_html("error rate &lt; 1 in 340 kb, measured"))

    def test_an_over_long_summary_is_truncated(self) -> None:
        """Some feeds put the whole article in the description.

        Storing it makes the licence position of a self-interested publisher far
        less comfortable than storing a summary.
        """
        text = strip_html("word " * 2000)
        assert text is not None
        assert len(text) <= MAX_SUMMARY_CHARACTERS + 1
        assert text.endswith("…")

    def test_empty_input_is_none(self) -> None:
        assert strip_html("") is None
        assert strip_html(None) is None


class TestDateParsing:
    def test_rfc_822_as_rss_specifies(self) -> None:
        parsed = parse_feed_datetime("Tue, 15 Sep 2026 14:30:00 +0000")
        assert parsed == datetime(2026, 9, 15, 14, 30, tzinfo=UTC)

    def test_rfc_3339_as_atom_specifies(self) -> None:
        assert parse_feed_datetime("2026-09-16T10:00:00Z") == datetime(
            2026, 9, 16, 10, 0, tzinfo=UTC
        )

    def test_a_naive_timestamp_is_assumed_utc(self) -> None:
        assert parse_feed_datetime("2026-09-16T10:00:00") == datetime(
            2026, 9, 16, 10, 0, tzinfo=UTC
        )

    def test_an_unparseable_date_is_none_not_an_exception(self) -> None:
        """One bad date must not cost the other thirty-nine entries."""
        assert parse_feed_datetime("last Thursday") is None
        assert parse_feed_datetime(None) is None


class TestRssParsing:
    @pytest.fixture
    def feed(self) -> str:
        return (FIXTURES / "doe_news.xml").read_text(encoding="utf-8")

    def test_entries_are_parsed(self, feed: str) -> None:
        documents = parse_feed(feed)
        assert [d.title for d in documents] == [
            "National Lab Sustains Plasma for 12 Minutes in Compact Tokamak Test",
            "Grid-Scale Sodium-Ion Battery Installed at Three Utility Sites",
            "An Entry With No Date At All",
        ]

    def test_the_guid_becomes_the_external_id(self, feed: str) -> None:
        """A feed's own identifier is more stable than its URL."""
        assert parse_feed(feed)[0].external_id == "energy.gov/node/4481920"

    def test_html_in_the_description_is_stripped(self, feed: str) -> None:
        abstract = parse_feed(feed)[0].abstract
        assert abstract is not None
        assert "<strong>" not in abstract
        assert "12 minutes" in abstract

    def test_an_entry_without_a_link_is_dropped(self, feed: str) -> None:
        """There is nothing to cite, so there is nothing to store."""
        assert all("no link" not in d.title.lower() for d in parse_feed(feed))

    def test_the_author_is_taken_from_dublin_core(self, feed: str) -> None:
        assert parse_feed(feed)[0].authors == [{"name": "Office of Science"}]


class TestAtomParsing:
    @pytest.fixture
    def feed(self) -> str:
        return (FIXTURES / "deepmind_blog.atom").read_text(encoding="utf-8")

    def test_entries_are_parsed(self, feed: str) -> None:
        assert len(parse_feed(feed)) == 2

    def test_the_alternate_link_is_preferred_over_the_edit_link(self, feed: str) -> None:
        """Atom offers several links; only one is the page a human reads."""
        assert parse_feed(feed)[0].url == "https://example-lab.org/blog/long-horizon-agent"

    def test_the_atom_id_becomes_the_external_id(self, feed: str) -> None:
        assert parse_feed(feed)[0].external_id == "tag:example-lab.org,2026:blog/long-horizon-agent"

    def test_published_is_preferred_over_updated(self, feed: str) -> None:
        """An edit is not a republication; the original date is the fact."""
        assert parse_feed(feed)[0].published_at == datetime(2026, 9, 16, 10, 0, tzinfo=UTC)

    def test_content_is_used_when_there_is_no_summary(self, feed: str) -> None:
        assert parse_feed(feed)[1].abstract is not None

    def test_the_atom_author_name_is_read(self, feed: str) -> None:
        assert parse_feed(feed)[0].authors == [{"name": "Research Team"}]


class TestDiscovery:
    def test_entries_older_than_the_window_are_skipped(self) -> None:
        feed = (FIXTURES / "deepmind_blog.atom").read_text(encoding="utf-8")
        with client_for(feed) as client:
            fetcher = RssFetcher(client, url="https://example-lab.org/blog/feed.atom")
            titles = [d.title for d in fetcher.discover(datetime(2026, 9, 1, tzinfo=UTC))]
        assert titles == ["A Long-Horizon Agent Completes 40-Step Software Tasks"]

    def test_an_undated_entry_is_kept(self) -> None:
        """A missing date is usually a publisher's omission, not an old document.

        Dropping it silently would lose real announcements; triage sees it with
        published_at NULL and can judge.
        """
        feed = (FIXTURES / "doe_news.xml").read_text(encoding="utf-8")
        with client_for(feed) as client:
            fetcher = RssFetcher(client, url="https://www.energy.gov/articles/feed")
            titles = [d.title for d in fetcher.discover(datetime(2026, 9, 10, tzinfo=UTC))]
        assert "An Entry With No Date At All" in titles
        assert "Grid-Scale Sodium-Ion Battery Installed at Three Utility Sites" not in titles

    def test_the_same_window_yields_the_same_ids(self) -> None:
        """Idempotency is what makes a re-run insert nothing."""
        feed = (FIXTURES / "doe_news.xml").read_text(encoding="utf-8")
        since = datetime(2026, 9, 1, tzinfo=UTC)
        with client_for(feed) as client:
            fetcher = RssFetcher(client, url="https://www.energy.gov/articles/feed")
            first = [d.external_id for d in fetcher.discover(since)]
            second = [d.external_id for d in fetcher.discover(since)]
        assert first == second

    def test_a_malformed_feed_raises_rather_than_returning_nothing(self) -> None:
        """Silence would look identical to a quiet week."""
        with client_for("<rss><channel><item><title>unclosed") as client:
            fetcher = RssFetcher(client, url="https://example.org/feed")
            with pytest.raises(Exception, match=r"(?i)mismatch|no element|syntax"):
                list(fetcher.discover(datetime(2026, 9, 1, tzinfo=UTC)))
