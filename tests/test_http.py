"""Outbound HTTP safety controls (docs/07 section L.2)."""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest

from radar.pipeline.http import (
    ResponseTooLargeError,
    SafeHttpClient,
    UnsafeUrlError,
    assert_url_is_safe,
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
        transport = httpx.MockTransport(lambda r: httpx.Response(503))
        with (
            SafeHttpClient(contact="a@b.org", client=httpx.Client(transport=transport)) as client,
            pytest.raises(httpx.HTTPStatusError),
        ):
            client.get("https://export.arxiv.org/api/query")
