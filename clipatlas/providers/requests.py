"""Smooth, bounded retries for the library's existing HTTP providers."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from clipatlas.providers.errors import ProviderRateLimitError, ProviderRequestError

logger = logging.getLogger(__name__)


class TransientProviderError(ProviderRequestError):
    retry_after: float = 0.0


def check_retryable_response(response: httpx.Response) -> None:
    if response.status_code not in {429, 500, 502, 503, 504}:
        return
    error = (ProviderRateLimitError if response.status_code == 429 else TransientProviderError)(
        f"upstream returned HTTP {response.status_code}"
    )
    raw = response.headers.get("Retry-After", "")
    delay = 0.0
    try:
        delay = float(raw)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            pass
    # A very long Retry-After is surfaced for a later resume, not ignored or slept forever.
    error.retry_after = max(0.0, delay)
    raise error


class RequestPolicy:
    def __init__(self, *, rpm: int, max_retries: int = 3, label: str = "cloud") -> None:
        if rpm < 1 or max_retries < 0:
            raise ValueError("invalid request limits")
        self._interval = 60.0 / rpm
        self._lock = asyncio.Lock()
        self._next = 0.0
        self._max_retries = max_retries
        self._label = label

    async def run[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(self._max_retries + 1):
            queued = time.monotonic()
            async with self._lock:
                await asyncio.sleep(max(0.0, self._next - time.monotonic()))
                self._next = time.monotonic() + self._interval
            started = time.monotonic()
            try:
                result = await operation()
                logger.info("%s request wait=%.3fs elapsed=%.3fs retries=%s", self._label,
                            started - queued, time.monotonic() - started, attempt)
                return result
            except (ProviderRateLimitError, ProviderRequestError, httpx.RequestError) as exc:
                transient = isinstance(exc, (ProviderRateLimitError, TransientProviderError,
                                             httpx.RequestError)) or isinstance(
                    exc.__cause__, httpx.RequestError,
                )
                requested = float(getattr(exc, "retry_after", 0.0))
                if not transient or attempt == self._max_retries or requested > 60:
                    raise
                delay = max(requested, min(30.0, 2.0 ** (attempt + 1)) + random.uniform(0, 0.5))
                logger.warning("%s retry=%s delay=%.2fs error=%s",
                               self._label, attempt + 1, delay, exc)
                async with self._lock:
                    self._next = max(self._next, time.monotonic() + delay)
        raise AssertionError("unreachable")
