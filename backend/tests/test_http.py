"""FetchClient tests (spec §8, §29, §39).

The contract under test: one unreachable source must never abort a run, retries
are bounded, transient and permanent failures are told apart, and per-host rate
limits are actually enforced.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.sources.http import RETRY_STATUSES, FetchClient, RateLimiter, _parse_retry_after


@pytest.fixture
def settings() -> Settings:
    # No waiting in tests. Backoff is capped at zero and the politeness budget is
    # raised out of the way, so retry logic runs at full speed. The real 20/minute
    # default is what made an earlier version of this file take 69 seconds — rate
    # limiting behaviour has its own dedicated tests below.
    return Settings(
        postgres_password="t",
        ingest_max_attempts=3,
        ingest_max_backoff_seconds=0,
        ingest_default_rate_limit_per_minute=100_000,
    )


def _client(handler, settings: Settings, limiter: RateLimiter | None = None) -> FetchClient:
    return FetchClient(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        limiter=limiter or RateLimiter(),
    )


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------

def test_successful_fetch(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "ParadigmIntelligence" in request.headers["user-agent"]
        return httpx.Response(200, content=b"<rss/>")

    result = _client(handler, settings).fetch("https://a.test/feed")
    assert result.ok
    assert result.status == 200
    assert result.content == b"<rss/>"
    assert result.error is None


# --------------------------------------------------------------------------
# failure isolation
# --------------------------------------------------------------------------

def test_network_error_returns_a_result_rather_than_raising(settings: Settings) -> None:
    """One dead source must not abort a run, so nothing propagates."""
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    result = _client(handler, settings).fetch("https://dead.test/feed")
    assert not result.ok
    assert result.content is None
    assert result.error and "ConnectError" in result.error


@pytest.mark.parametrize("status", sorted(RETRY_STATUSES))
def test_transient_statuses_are_retried_to_the_limit(status: int, settings: Settings) -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status)

    result = _client(handler, settings).fetch("https://a.test/feed")
    assert not result.ok
    assert calls["n"] == settings.ingest_max_attempts


def test_a_transient_failure_then_success(settings: Settings) -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    result = _client(handler, settings).fetch("https://a.test/feed")
    assert result.ok
    assert calls["n"] == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 451])
def test_permanent_failures_are_not_retried(status: int, settings: Settings) -> None:
    """A 403 is an answer, not a hiccup. Retrying it wastes the politeness budget."""
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status)

    result = _client(handler, settings).fetch("https://a.test/feed")
    assert not result.ok
    assert result.status == status
    assert calls["n"] == 1


def test_retries_are_bounded(settings: Settings) -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow")

    _client(handler, settings).fetch("https://a.test/feed")
    assert calls["n"] == settings.ingest_max_attempts


# --------------------------------------------------------------------------
# resource limits
# --------------------------------------------------------------------------

def test_oversized_responses_are_truncated_not_dropped(settings: Settings) -> None:
    """A feed's early entries are the recent ones, so truncation beats discarding."""
    capped = Settings(postgres_password="t", ingest_max_response_bytes=100,
                      ingest_max_backoff_seconds=0,
                      ingest_default_rate_limit_per_minute=100_000)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    result = _client(handler, capped).fetch("https://a.test/feed")
    assert result.ok
    assert result.content is not None
    assert len(result.content) == 100


# --------------------------------------------------------------------------
# rate limiting
# --------------------------------------------------------------------------

def test_rate_limiter_spaces_requests_to_the_same_host() -> None:
    limiter = RateLimiter()
    # 60/minute means a one-second interval; the first call is free.
    assert limiter.wait("a.test", 60) == 0.0
    # The second call computes a delay; assert on the bookkeeping rather than
    # sleeping for a second in a test.
    assert limiter._next_allowed["a.test"] > 0


def test_rate_limiter_is_per_host() -> None:
    """Several configured sources can share a host; it is the host that throttles."""
    limiter = RateLimiter()
    limiter.wait("a.test", 60)
    # A different host is unaffected by the first host's budget.
    assert limiter.wait("b.test", 60) == 0.0


def test_zero_rate_limit_means_unlimited() -> None:
    limiter = RateLimiter()
    for _ in range(5):
        assert limiter.wait("a.test", 0) == 0.0


def test_client_passes_the_configured_rate_limit(settings: Settings) -> None:
    seen: list[tuple[str, float]] = []

    class RecordingLimiter(RateLimiter):
        def wait(self, host: str, requests_per_minute: float) -> float:
            seen.append((host, requests_per_minute))
            return 0.0

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    client = _client(handler, settings, limiter=RecordingLimiter())
    client.fetch("https://a.test/feed", requests_per_minute=7)
    assert seen == [("a.test", 7)]


def test_client_defaults_to_the_configured_rate_limit(settings: Settings) -> None:
    seen: list[float] = []

    class RecordingLimiter(RateLimiter):
        def wait(self, host: str, requests_per_minute: float) -> float:
            seen.append(requests_per_minute)
            return 0.0

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    _client(handler, settings, RecordingLimiter()).fetch("https://a.test/f")
    assert seen == [settings.ingest_default_rate_limit_per_minute]


# --------------------------------------------------------------------------
# Retry-After
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("header", "expected"),
    [("5", 5.0), ("0", 0.0), ("2.5", 2.5), (None, None), ("", None),
     ("Wed, 21 Oct 2026 07:28:00 GMT", None), ("-1", None)],
)
def test_retry_after_parsing(header: str | None, expected: float | None) -> None:
    assert _parse_retry_after(header) == expected


def test_context_manager_closes_its_own_client(settings: Settings) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    inner = httpx.Client(transport=httpx.MockTransport(handler))
    with FetchClient(settings, client=inner) as client:
        assert client.fetch("https://a.test/f").ok
    # An injected client is not owned, so it stays open for its owner to close.
    assert not inner.is_closed
    inner.close()
