"""Outbound HTTP safety controls (docs/07 section L.2)."""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest

from radar.pipeline.http import (
    TRANSIENT_STATUSES,
    ResponseTooLargeError,
    SafeHttpClient,
    TransientHttpError,
    UnsafeUrlError,
    assert_url_is_safe,
    backoff_delay,
)


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every hostname to a public address, so tests need no network."""

    def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


class TestUrlSafety:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.org/x",
            "gopher://example.org",
            "data:text/plain,hello",
        ],
    )
    def test_non_http_schemes_are_refused(self, url: str) -> None:
        with pytest.raises(UnsafeUrlError, match="scheme"):
            assert_url_is_safe(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://localhost:8000/",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
            "http://10.0.0.5/internal",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://[::1]/",
            "http://0.0.0.0/",
        ],
    )
    def test_private_and_loopback_addresses_are_refused(self, url: str) -> None:
        with pytest.raises(UnsafeUrlError, match=r"non-public|resolve"):
            assert_url_is_safe(url)

    def test_a_public_host_is_allowed(self, public_dns: None) -> None:
        assert_url_is_safe("https://export.arxiv.org/api/query")

    def test_dns_rebinding_to_a_private_address_is_caught(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A public-looking name whose A record points inside the network."""

        def rebinding(host: str, *args: Any, **kwargs: Any) -> list[Any]:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", rebinding)
        with pytest.raises(UnsafeUrlError, match="non-public"):
            assert_url_is_safe("https://totally-legitimate.example.org/feed")


class TestSafeHttpClient:
    def test_a_contact_address_is_required(self) -> None:
        with pytest.raises(ValueError, match="contact address"):
            SafeHttpClient(contact=None)

    def test_the_user_agent_names_the_project_and_contact(self, public_dns: None) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, text="<feed/>")

        transport = httpx.MockTransport(handler)
        with SafeHttpClient(
            contact="someone@example.org", client=httpx.Client(transport=transport)
        ) as client:
            client.get("https://export.arxiv.org/api/query")

        assert "FutureTechRadar" in seen["user-agent"]
        assert "someone@example.org" in seen["user-agent"]

    def test_an_oversized_response_is_refused(self, public_dns: None) -> None:
        transport = httpx.MockTransport(lambda r: httpx.Response(200, text="x" * 5000))
        with (
            SafeHttpClient(
                contact="a@b.org", client=httpx.Client(transport=transport), max_bytes=1000
            ) as client,
            pytest.raises(ResponseTooLargeError, match="over the 1000 cap"),
        ):
            client.get("https://export.arxiv.org/api/query")

    def test_a_redirect_to_a_private_address_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Following redirects blindly is how an SSRF filter gets bypassed."""

        def dns(host: str, *args: Any, **kwargs: Any) -> list[Any]:
            address = "127.0.0.1" if host == "internal.example.org" else "93.184.216.34"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

        monkeypatch.setattr(socket, "getaddrinfo", dns)
        transport = httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://internal.example.org/x"})
        )
        with (
            SafeHttpClient(contact="a@b.org", client=httpx.Client(transport=transport)) as client,
            pytest.raises(UnsafeUrlError, match="non-public"),
        ):
            client.get("https://export.arxiv.org/api/query")

    def test_a_redirect_loop_stops(self, public_dns: None) -> None:
        transport = httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "https://export.arxiv.org/again"})
        )
        with (
            SafeHttpClient(contact="a@b.org", client=httpx.Client(transport=transport)) as client,
            pytest.raises(UnsafeUrlError, match="too many redirects"),
        ):
            client.get("https://export.arxiv.org/api/query")

    def test_an_http_error_is_raised(self, public_dns: None) -> None:
        # 404, not 503: transient statuses are retried now, and retry exhaustion
        # has its own test. This one is about a permanent error propagating.
        transport = httpx.MockTransport(lambda r: httpx.Response(404))
        with (
            SafeHttpClient(contact="a@b.org", client=httpx.Client(transport=transport)) as client,
            pytest.raises(httpx.HTTPStatusError),
        ):
            client.get("https://export.arxiv.org/api/query")


class RecordingSleep:
    """Captures backoff delays instead of spending them."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class TestTransientRetries:
    """arXiv answers 406 when shedding load, and the same request then succeeds.

    Treating that as a hard client error made three categories fail on every
    run while their neighbours, fetched seconds apart, returned 200.
    """

    def _client(
        self, responses: list[httpx.Response], *, sleep: RecordingSleep, max_attempts: int = 4
    ) -> SafeHttpClient:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            index = min(calls["n"], len(responses) - 1)
            calls["n"] += 1
            return responses[index]

        return SafeHttpClient(
            contact="a@b.org",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_attempts=max_attempts,
            sleep=sleep,
        )

    def test_406_is_treated_as_a_throttle_and_retried(self, public_dns: None) -> None:
        sleep = RecordingSleep()
        client = self._client(
            [httpx.Response(406), httpx.Response(200, text="<feed/>")], sleep=sleep
        )
        result = client.get("https://export.arxiv.org/api/query")
        assert result.text == "<feed/>"
        assert len(sleep.delays) == 1, "it waited once before succeeding"

    @pytest.mark.parametrize("status", sorted(TRANSIENT_STATUSES))
    def test_every_transient_status_is_retried(self, status: int, public_dns: None) -> None:
        sleep = RecordingSleep()
        client = self._client([httpx.Response(status), httpx.Response(200, text="ok")], sleep=sleep)
        assert client.get("https://export.arxiv.org/api/query").text == "ok"

    def test_a_permanent_error_is_not_retried(self, public_dns: None) -> None:
        """404 means the URL is wrong; waiting will not change that."""
        sleep = RecordingSleep()
        client = self._client([httpx.Response(404)], sleep=sleep)
        with pytest.raises(httpx.HTTPStatusError):
            client.get("https://export.arxiv.org/api/query")
        assert sleep.delays == [], "no time wasted on a permanent failure"

    def test_it_gives_up_after_the_attempt_budget(self, public_dns: None) -> None:
        sleep = RecordingSleep()
        client = self._client([httpx.Response(406)], sleep=sleep, max_attempts=3)
        with pytest.raises(httpx.HTTPStatusError):
            client.get("https://export.arxiv.org/api/query")
        assert len(sleep.delays) == 2, "slept between attempts, not after the last"

    def test_retry_after_is_honoured_over_backoff(self, public_dns: None) -> None:
        sleep = RecordingSleep()
        client = self._client(
            [
                httpx.Response(429, headers={"retry-after": "7"}),
                httpx.Response(200, text="ok"),
            ],
            sleep=sleep,
        )
        client.get("https://export.arxiv.org/api/query")
        assert sleep.delays == [7.0]

    def test_an_unparseable_retry_after_falls_back_to_backoff(self, public_dns: None) -> None:
        sleep = RecordingSleep()
        client = self._client(
            [
                httpx.Response(503, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
                httpx.Response(200, text="ok"),
            ],
            sleep=sleep,
        )
        client.get("https://export.arxiv.org/api/query")
        assert len(sleep.delays) == 1
        assert sleep.delays[0] >= 0

    def test_the_accept_header_names_atom(self, public_dns: None) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, text="<feed/>")

        with SafeHttpClient(
            contact="a@b.org", client=httpx.Client(transport=httpx.MockTransport(handler))
        ) as client:
            client.get("https://export.arxiv.org/api/query")
        assert "atom" in seen["accept"]


class TestBackoffDelay:
    def test_it_grows_with_each_attempt(self) -> None:
        early = max(backoff_delay(0) for _ in range(200))
        late = max(backoff_delay(3) for _ in range(200))
        assert late > early

    def test_it_is_jittered_rather_than_fixed(self) -> None:
        """Without jitter, every source on a host retries at the same instant."""
        samples = {backoff_delay(2) for _ in range(50)}
        assert len(samples) > 1

    def test_it_is_capped(self) -> None:
        assert all(backoff_delay(50) <= 60.0 for _ in range(100))

    def test_it_is_never_negative(self) -> None:
        assert all(backoff_delay(n) >= 0 for n in range(10))


def test_transient_error_type_is_exported() -> None:
    assert issubclass(TransientHttpError, RuntimeError)
