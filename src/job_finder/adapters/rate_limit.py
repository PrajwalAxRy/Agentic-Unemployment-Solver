"""Per-host request pacing and concurrency limiting.

``HttpPolicy`` had timeout, retry and backoff but no ``min_interval`` or concurrency cap,
so nothing stopped the scan hammering a single host. That is not hypothetical: **39
Greenhouse companies all resolve to ``boards-api.greenhouse.io``** and were fetched
back-to-back, as were 28 Ashby and 25 Workday companies against their own shared hosts
(``to_change.md`` 6.6, 9.7).

This becomes acute in the same phase that adds parallelism. A thread pool over companies
multiplies simultaneous requests to those same few hosts, so the limiter has to land
with -- or before -- the pool.

Design notes:

* **Keyed by host, not by company.** The company is irrelevant to the server being
  protected; the host is what has the rate limit.
* **Lives in the client**, so every adapter inherits pacing without individual changes.
  Asking 36 adapters to remember to throttle is the same mistake as asking them to
  remember to normalize.
* **Holds the host slot across the whole request**, including retries, so a retry storm
  cannot bypass the interval.
* 5.2 states the principle this implements: exhaustiveness over speed. A slow scan is
  acceptable; an incomplete one is not, because truncation feeds the staleness logic and
  can close live jobs.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit


class HostRateLimiter:
    """Enforce a minimum interval and a concurrency cap per host.

    Thread-safe: the scan runs a bounded thread pool over companies, and several of those
    threads routinely target the same host.
    """

    def __init__(
        self,
        *,
        min_interval_seconds: float = 0.0,
        max_concurrent_per_host: int = 0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        if max_concurrent_per_host < 0:
            raise ValueError("max_concurrent_per_host cannot be negative")
        self._min_interval = min_interval_seconds
        self._max_concurrent = max_concurrent_per_host
        self._sleep = sleep
        self._monotonic = monotonic
        self._guard = threading.Lock()
        self._next_available: dict[str, float] = defaultdict(float)
        self._semaphores: dict[str, threading.Semaphore] = {}

    def _semaphore(self, host: str) -> threading.Semaphore | None:
        if self._max_concurrent <= 0:
            return None
        with self._guard:
            semaphore = self._semaphores.get(host)
            if semaphore is None:
                semaphore = threading.Semaphore(self._max_concurrent)
                self._semaphores[host] = semaphore
            return semaphore

    def _reserve(self, host: str) -> float:
        """Claim the next send slot for ``host`` and return how long to wait for it."""
        if self._min_interval <= 0:
            return 0.0
        with self._guard:
            now = self._monotonic()
            earliest = self._next_available[host]
            start = max(now, earliest)
            # Reserve before releasing the guard so concurrent callers queue behind this
            # slot rather than all computing the same one.
            self._next_available[host] = start + self._min_interval
            return max(0.0, start - now)

    def penalize(self, url: str, seconds: float) -> None:
        """Push a host's next send time out, e.g. after an explicit ``Retry-After``.

        Applies to the host rather than the single request, so one 429 slows every
        company sharing that host instead of each discovering the limit separately.
        """
        if seconds <= 0:
            return
        host = host_of(url)
        with self._guard:
            self._next_available[host] = max(
                self._next_available[host], self._monotonic() + seconds
            )

    @contextmanager
    def hold(self, url: str) -> Iterator[None]:
        """Acquire the host slot, pace the request, and release on exit."""
        host = host_of(url)
        semaphore = self._semaphore(host)
        if semaphore is not None:
            semaphore.acquire()
        try:
            delay = self._reserve(host)
            if delay > 0:
                self._sleep(delay)
            yield
        finally:
            if semaphore is not None:
                semaphore.release()


def host_of(url: str) -> str:
    """Return the lowercase host for rate-limit keying, or the raw URL if unparseable."""
    return urlsplit(url).netloc.lower() or url
