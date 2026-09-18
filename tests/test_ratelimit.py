"""Rate limiting — the promise we make to source operators."""

from __future__ import annotations

from radar.pipeline.ratelimit import LimiterRegistry, MinIntervalLimiter


class RecordingSleep:
    """Stands in for time.sleep so tests do not spend real seconds."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class TestMinIntervalLimiter:
    def test_the_first_call_does_not_wait(self) -> None:
        sleep = RecordingSleep()
        limiter = MinIntervalLimiter(3.0, sleep=sleep)
        assert limiter.acquire() == 0.0
        assert sleep.calls == []

    def test_a_second_immediate_call_waits(self) -> None:
        sleep = RecordingSleep()
        limiter = MinIntervalLimiter(3.0, sleep=sleep)
        limiter.acquire()
        waited = limiter.acquire()
        assert waited > 0
        assert len(sleep.calls) == 1
        # arXiv requires three seconds between requests; allow for the
        # microseconds spent between the two acquire calls.
        assert 2.9 <= sleep.calls[0] <= 3.0

    def test_a_zero_interval_never_waits(self) -> None:
        sleep = RecordingSleep()
        limiter = MinIntervalLimiter(0.0, sleep=sleep)
        for _ in range(5):
            limiter.acquire()
        assert sleep.calls == []

    def test_it_works_as_a_context_manager(self) -> None:
        sleep = RecordingSleep()
        limiter = MinIntervalLimiter(1.0, sleep=sleep)
        with limiter:
            pass
        with limiter:
            pass
        assert len(sleep.calls) == 1


class TestLimiterRegistry:
    def test_every_source_on_a_host_shares_one_limiter(self) -> None:
        """The reason this class exists: eleven arXiv categories are one server."""
        registry = LimiterRegistry()
        first = registry.for_host("export.arxiv.org", 3.0)
        second = registry.for_host("export.arxiv.org", 3.0)
        assert first is second

    def test_different_hosts_get_different_limiters(self) -> None:
        registry = LimiterRegistry()
        arxiv = registry.for_host("export.arxiv.org", 3.0)
        biorxiv = registry.for_host("api.biorxiv.org", 1.0)
        assert arxiv is not biorxiv
        assert sorted(registry.hosts()) == ["api.biorxiv.org", "export.arxiv.org"]

    def test_the_strictest_interval_wins(self) -> None:
        """A lenient source must not loosen the limit a stricter one asked for."""
        registry = LimiterRegistry()
        registry.for_host("export.arxiv.org", 1.0)
        limiter = registry.for_host("export.arxiv.org", 3.0)
        assert limiter.min_interval == 3.0

    def test_a_lenient_request_does_not_relax_an_existing_limit(self) -> None:
        registry = LimiterRegistry()
        registry.for_host("export.arxiv.org", 3.0)
        limiter = registry.for_host("export.arxiv.org", 0.5)
        assert limiter.min_interval == 3.0
