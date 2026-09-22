"""Outbound HTTP with the safety controls from docs/07-security-privacy.md.

Fetched URLs come from third-party feeds, so they are attacker-influenced input.
This module is the single choke point where that risk is handled: no private
network addresses, no unbounded downloads, no silent redirect escapes, and an
honest User-Agent that names the project and a contact address.
"""

from __future__ import annotations

import ipaddress
import json
import random
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog

from radar.pipeline.ratelimit import MinIntervalLimiter

log = structlog.get_logger(__name__)

USER_AGENT_TEMPLATE = (
    "FutureTechRadar/0.1 (+https://github.com/sanathSK07/futuretech-radar; {contact})"
)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
"""A ceiling, not a budget: almost every response is kilobytes.

Raised from 5 MB once harvesting moved to OAI-PMH. A single ListRecords page
for the whole ``cs`` set measured 4,076,389 bytes on 2026-09-21 — under the
old cap, but not by enough to be comfortable on a busy day.
"""
ALLOWED_SCHEMES = frozenset({"http", "https"})

TRANSIENT_STATUSES = frozenset({406, 408, 425, 429, 500, 502, 503, 504})
"""Statuses worth retrying rather than failing the source on.

406 is here for a specific, verified reason, though not the one first written
down. export.arxiv.org's search API sits behind an edge cache that serves stored
responses and answers 406 to anything needing an origin fetch: a 200 carries
``age`` and ``x-cache: MISS, HIT, HIT``, the 406 beside it carries
``x-cache: MISS, MISS`` and ``cache-control: private, no-store``. Retrying still
helps, because a URL another client has since warmed starts answering — which is
what made this look like load shedding for a week. Harvesting now goes through
OAI-PMH, which is not cached this way; see fetchers/arxiv_oai.py.
"""

DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_BACKOFF_BASE_SECONDS = 3.0
MAX_BACKOFF_SECONDS = 60.0
"""Four attempts over roughly fifteen seconds was not enough.

The first full run with every source active lost five of eleven arXiv
categories to 406, each having exhausted its retries inside twelve seconds. A
different five failed on the previous run, which is what says the status is
load shedding rather than anything about those categories. Six attempts with a
three-second base spends up to about two minutes on a shedding source, and only
on one that is actually failing.
"""


class UnsafeUrlError(ValueError):
    """The URL points somewhere we refuse to fetch from."""


class ResponseTooLargeError(ValueError):
    """The response exceeded the byte cap."""


class InvalidJsonError(ValueError):
    """A source that should answer JSON answered something else."""


class TransientHttpError(RuntimeError):
    """A retryable status kept recurring until the attempts ran out."""


def backoff_delay(attempt: int, *, base: float = DEFAULT_BACKOFF_BASE_SECONDS) -> float:
    """Exponential backoff with full jitter, capped.

    Jitter matters when several sources share a host: without it, every retry
    after a load-shedding event lands at the same instant and sheds load again.
    """
    ceiling = min(base * (2**attempt), MAX_BACKOFF_SECONDS)
    return random.uniform(0, ceiling)  # noqa: S311 - jitter, not cryptography


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Honour a numeric Retry-After header when the server sends one."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


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

    def json(self) -> Any:
        """Parse the body as JSON.

        Raises InvalidJsonError naming the URL, because an API that starts
        answering with an HTML error page otherwise produces a decode error
        several frames away from anything that identifies the source.
        """
        try:
            return json.loads(self.text)
        except ValueError as exc:
            preview = self.text[:120].replace("\n", " ")
            raise InvalidJsonError(
                f"{self.url} did not return JSON ({self.content_type}): {preview!r}"
            ) from exc


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
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not contact:
            raise ValueError(
                "a contact address is required before fetching: set RADAR_CRAWLER_CONTACT "
                "so source operators can reach us"
            )
        self.limiter = limiter
        self.max_bytes = max_bytes
        self.max_attempts = max(1, max_attempts)
        self._sleep = sleep or time.sleep
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,  # redirects are re-validated by hand below
        )
        # Set unconditionally rather than only on the client we build: an
        # injected client would otherwise fetch anonymously, and identifying
        # ourselves to source operators is not optional.
        self._client.headers["User-Agent"] = USER_AGENT_TEMPLATE.format(contact=contact)
        # Assigned rather than setdefault: httpx installs a default "*/*" of its own,
        # which setdefault would treat as a deliberate caller choice.
        self._client.headers["Accept"] = "application/atom+xml, application/xml, */*"
        self._client.follow_redirects = False

    def get(self, url: str, *, max_redirects: int = 3) -> FetchResult:
        """GET a URL, retrying transient failures with backoff.

        Retries wrap the whole redirect walk, so a throttled request is reissued
        from its original URL rather than from wherever the last hop left off.
        """
        last_status: int | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._get_once(url, max_redirects=max_redirects)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in TRANSIENT_STATUSES or attempt == self.max_attempts - 1:
                    raise
                last_status = status
                delay = retry_after_seconds(exc.response) or backoff_delay(attempt)
                log.warning(
                    "transient_http_status",
                    url=url,
                    status=status,
                    attempt=attempt + 1,
                    of=self.max_attempts,
                    retrying_in_seconds=round(delay, 1),
                )
                self._sleep(delay)

        raise TransientHttpError(
            f"{url} kept returning {last_status} after {self.max_attempts} attempts"
        )

    def _get_once(self, url: str, *, max_redirects: int = 3) -> FetchResult:
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
