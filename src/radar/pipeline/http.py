"""Outbound HTTP with the safety controls from docs/07-security-privacy.md.

Fetched URLs come from third-party feeds, so they are attacker-influenced input.
This module is the single choke point where that risk is handled: no private
network addresses, no unbounded downloads, no silent redirect escapes, and an
honest User-Agent that names the project and a contact address.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import structlog

from radar.pipeline.ratelimit import MinIntervalLimiter

log = structlog.get_logger(__name__)

USER_AGENT_TEMPLATE = (
    "FutureTechRadar/0.1 (+https://github.com/sanathSK07/futuretech-radar; {contact})"
)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeUrlError(ValueError):
    """The URL points somewhere we refuse to fetch from."""


class ResponseTooLargeError(ValueError):
    """The response exceeded the byte cap."""


def _is_forbidden_address(address: str) -> bool:
    """True for addresses that must never be fetched.

    Blocks loopback, link-local (including the 169.254.169.254 cloud metadata
    endpoint), private ranges, reserved and unspecified addresses.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_url_is_safe(url: str) -> None:
    """Reject non-HTTP schemes and hosts that resolve into private space.

    Resolution happens here rather than trusting the hostname, so a public name
    with a private A record (DNS rebinding) is caught.
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme {parts.scheme!r} is not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")

    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host {host!r}: {exc}") from exc

    for family, _type, _proto, _canonname, sockaddr in resolved:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = str(sockaddr[0])
        if _is_forbidden_address(address):
            raise UnsafeUrlError(f"host {host!r} resolves to non-public address {address}")


@dataclass(frozen=True)
class FetchResult:
    """A successfully fetched body."""

    url: str
    status_code: int
    text: str
    content_type: str | None


class SafeHttpClient:
    """A rate-limited HTTP client that refuses unsafe URLs and huge bodies."""

    def __init__(
        self,
        *,
        contact: str | None,
        limiter: MinIntervalLimiter | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        client: httpx.Client | None = None,
    ) -> None:
        if not contact:
            raise ValueError(
                "a contact address is required before fetching: set RADAR_CRAWLER_CONTACT "
                "so source operators can reach us"
            )
        self.limiter = limiter
        self.max_bytes = max_bytes
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,  # redirects are re-validated by hand below
        )
        # Set unconditionally rather than only on the client we build: an
        # injected client would otherwise fetch anonymously, and identifying
        # ourselves to source operators is not optional.
        self._client.headers["User-Agent"] = USER_AGENT_TEMPLATE.format(contact=contact)
        self._client.follow_redirects = False

    def get(self, url: str, *, max_redirects: int = 3) -> FetchResult:
        """GET a URL, validating it and every redirect hop."""
        current = url
        for hop in range(max_redirects + 1):
            assert_url_is_safe(current)
            if self.limiter is not None:
                waited = self.limiter.acquire()
                if waited:
                    log.debug("rate_limited", url=current, waited_seconds=round(waited, 2))

            response = self._client.get(current)

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeUrlError(f"redirect from {current} had no Location header")
                current = str(httpx.URL(current).join(location))
                log.debug("redirect", hop=hop, to=current)
                continue

            response.raise_for_status()
            body = response.content
            if len(body) > self.max_bytes:
                raise ResponseTooLargeError(
                    f"{current} returned {len(body)} bytes, over the {self.max_bytes} cap"
                )
            return FetchResult(
                url=current,
                status_code=response.status_code,
                text=body.decode(response.encoding or "utf-8", errors="replace"),
                content_type=response.headers.get("content-type"),
            )

        raise UnsafeUrlError(f"too many redirects starting from {url}")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SafeHttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
