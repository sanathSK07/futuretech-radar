"""Rate limiting for outbound fetches.

Source operators publish rate limits and we honour them: arXiv's terms require
"no more than one request every three seconds, and limit requests to a single
connection at a time". Politeness here is not optional — it is the condition on
which access continues.
"""

from __future__ import annotations

import threading
import time
from types import TracebackType


class MinIntervalLimiter:
    """Enforce a minimum wall-clock interval between calls.

    Thread-safe and re-entrant across a process. Serialising on the lock also
    gives the "single connection at a time" behaviour arXiv asks for, since no
    two callers can be inside ``acquire`` concurrently.
    """

    def __init__(self, min_interval_seconds: float, *, sleep: object = None) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must not be negative")
        self.min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._last_call: float | None = None
        # Injectable clock/sleep so tests do not spend real seconds.
        self._sleep = sleep if callable(sleep) else time.sleep
        self._monotonic = time.monotonic

    def acquire(self) -> float:
        """Block until the next call is allowed. Returns the seconds waited."""
        with self._lock:
            now = self._monotonic()
            waited = 0.0
            if self._last_call is not None:
                elapsed = now - self._last_call
                remaining = self.min_interval - elapsed
                if remaining > 0:
                    self._sleep(remaining)
                    waited = remaining
                    now = self._monotonic()
            self._last_call = now
            return waited

    def __enter__(self) -> MinIntervalLimiter:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class LimiterRegistry:
    """Hands out one limiter per host, shared by every source on that host.

    This matters more than it looks. Eleven arXiv categories are eleven sources
    in the registry, but they are one server: a limiter per source would issue
    eleven requests every three seconds and breach arXiv's terms immediately.
    Keying on the host — and keeping the strictest interval any source asked
    for — makes the politeness promise hold no matter how many categories are
    configured.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, MinIntervalLimiter] = {}
        self._lock = threading.Lock()

    def for_host(self, host: str, min_interval_seconds: float) -> MinIntervalLimiter:
        with self._lock:
            existing = self._limiters.get(host)
            if existing is None:
                limiter = MinIntervalLimiter(min_interval_seconds)
                self._limiters[host] = limiter
                return limiter
            if min_interval_seconds > existing.min_interval:
                existing.min_interval = min_interval_seconds
            return existing

    def hosts(self) -> list[str]:
        with self._lock:
            return sorted(self._limiters)
