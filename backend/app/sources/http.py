"""Polite, resilient HTTP fetching for source adapters.

Every network call an adapter makes goes through ``FetchClient``. It owns the
things that are easy to get wrong once per adapter and impossible to audit when
scattered: timeouts, bounded retries, per-host rate limiting, and a real
User-Agent.

Rate limiting is per *host*, not per source, because several configured sources
can sit on one publisher's domain and it is the host that will throttle us.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: Statuses worth trying again. 403/404 are answers, not hiccups.
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 509, 529})


class RateLimiter:
    """Minimum-interval limiter, keyed by host.

    Deliberately a sleeper rather than a queue: ingestion is a small sequential
    batch job, and blocking the one worker for a moment is the whole mechanism.
    """

    def __init__(self) -> None:
        self._next_allowed: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, requests_per_minute: float) -> float:
        """Block until another request to ``host`` is allowed. Returns seconds slept."""
        if requests_per_minute <= 0:
            return 0.0
        interval = 60.0 / requests_per_minute

        with self._lock:
            now = time.monotonic()
            earliest = self._next_allowed.get(host, 0.0)
            delay = max(0.0, earliest - now)
            self._next_allowed[host] = max(now, earliest) + interval

        if delay > 0:
            logger.debug("rate limit wait", extra={"host": host, "seconds": round(delay, 2)})
            time.sleep(delay)
        return delay


#: Shared across adapters so per-host limits actually hold for a whole run.
_LIMITER = RateLimiter()


@dataclass(slots=True)
class FetchResult:
    """Outcome of one fetch. Never raises for an HTTP-level failure."""

    url: str
    status: int | None
    content: bytes | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.content is not None


class FetchClient:
    """HTTP client for adapters.

    ``fetch`` returns a ``FetchResult`` rather than raising: one unreachable
    source must never abort an ingestion run, and forcing every adapter to
    remember its own try/except is how that rule gets broken.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
    ):
        self.settings = settings or get_settings()
        self._limiter = limiter or _LIMITER
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(self.settings.ingest_http_timeout),
            follow_redirects=True,
            # A publisher that redirects us in a loop is a misconfiguration, not
            # something to chase indefinitely.
            max_redirects=5,
        )

    @property
    def _headers(self) -> dict[str, str]:
        """Identification and content negotiation.

        Sent per request rather than baked into the client, so the polite
        User-Agent travels with the fetch policy and cannot be lost by injecting a
        differently-configured client.
        """
        return {
            "User-Agent": self.settings.ingest_user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, "
            "text/xml, text/html;q=0.9, */*;q=0.5",
            "Accept-Language": "en, ar;q=0.8",
        }

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FetchClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(
        self,
        url: str,
        *,
        requests_per_minute: float | None = None,
        max_attempts: int | None = None,
        max_bytes: int | None = None,
    ) -> FetchResult:
        """GET ``url`` politely, with bounded retries."""
        host = urlsplit(url).netloc.casefold() or url
        rpm = (
            requests_per_minute
            if requests_per_minute is not None
            else self.settings.ingest_default_rate_limit_per_minute
        )
        attempts = max_attempts or self.settings.ingest_max_attempts
        cap = max_bytes or self.settings.ingest_max_response_bytes

        backoff = 1.0
        last_error: str | None = None
        last_status: int | None = None

        for attempt in range(1, attempts + 1):
            self._limiter.wait(host, rpm)
            try:
                response = self._client.get(url, headers=self._headers)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                last_status = None
                logger.warning(
                    "fetch failed",
                    extra={"url": url, "attempt": attempt, "error": last_error[:200]},
                )
            else:
                last_status = response.status_code
                if response.status_code == 200:
                    content = response.content
                    if len(content) > cap:
                        # Truncate rather than discard: a feed's first entries are
                        # the recent ones, which is what we came for.
                        logger.warning(
                            "response truncated at byte cap",
                            extra={"url": url, "bytes": len(content), "cap": cap},
                        )
                        content = content[:cap]
                    return FetchResult(url=url, status=200, content=content)

                if response.status_code == 429:
                    # Honour Retry-After when the server tells us how long.
                    retry_after = _parse_retry_after(response.headers.get("retry-after"))
                    if retry_after is not None:
                        backoff = max(backoff, retry_after)

                last_error = f"HTTP {response.status_code}"
                if response.status_code not in RETRY_STATUSES:
                    logger.error(
                        "fetch rejected",
                        extra={"url": url, "status": response.status_code},
                    )
                    return FetchResult(url=url, status=response.status_code, content=None,
                                       error=last_error)
                logger.warning(
                    "fetch transient error",
                    extra={"url": url, "status": response.status_code, "attempt": attempt},
                )

            if attempt < attempts:
                time.sleep(min(backoff, self.settings.ingest_max_backoff_seconds))
                backoff *= 2

        return FetchResult(url=url, status=last_status, content=None, error=last_error)


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds form of ``Retry-After``. HTTP-date form is ignored as rare here."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
