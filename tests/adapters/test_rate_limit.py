"""Per-host pacing and concurrency limiting (to_change.md 5.2, 6.6, 9.7).

39 Greenhouse companies resolve to the same ``boards-api.greenhouse.io`` and were fetched
back-to-back with no pacing at all. Adding a thread pool over companies (6.5) multiplies
that onto the same few shared ATS hosts, so the limiter has to be thread-safe and keyed by
host rather than by company.
"""

from __future__ import annotations

import threading

import pytest

from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy
from job_finder.adapters.rate_limit import HostRateLimiter, host_of


class FakeClock:
    """Monotonic clock that only advances when sleep() is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _limiter(clock: FakeClock, **kwargs: float | int) -> HostRateLimiter:
    return HostRateLimiter(sleep=clock.sleep, monotonic=clock.monotonic, **kwargs)


def test_host_extraction_is_case_insensitive_and_port_aware() -> None:
    assert host_of("https://Boards-API.greenhouse.io/v1/boards/x") == "boards-api.greenhouse.io"
    assert host_of("https://example.com:8443/a") == "example.com:8443"
    assert host_of("not a url") == "not a url"


def test_requests_to_the_same_host_are_paced() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_seconds=2.0)

    for _ in range(3):
        with limiter.hold("https://boards-api.greenhouse.io/v1/boards/a"):
            pass

    # First request is immediate; each subsequent one waits the full interval.
    assert clock.sleeps == [2.0, 2.0]


def test_different_hosts_do_not_block_each_other() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_seconds=5.0)

    with limiter.hold("https://boards-api.greenhouse.io/a"):
        pass
    with limiter.hold("https://jobs.ashbyhq.com/b"):
        pass

    assert clock.sleeps == [], "a different host must not inherit another host's interval"


def test_pacing_is_disabled_by_default() -> None:
    """Default policy must not change existing behaviour or slow any test."""
    clock = FakeClock()
    limiter = _limiter(clock)

    for _ in range(5):
        with limiter.hold("https://boards-api.greenhouse.io/a"):
            pass

    assert clock.sleeps == []


def test_retry_after_penalizes_the_whole_host() -> None:
    """One 429 must slow every company sharing the host.

    Otherwise all 39 Greenhouse companies rediscover the same limit individually.
    """
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_seconds=1.0)

    limiter.penalize("https://boards-api.greenhouse.io/v1/boards/a", 60.0)
    with limiter.hold("https://boards-api.greenhouse.io/v1/boards/DIFFERENT-COMPANY"):
        pass

    assert clock.sleeps == [60.0]


def test_concurrency_cap_limits_simultaneous_requests_per_host() -> None:
    limiter = HostRateLimiter(max_concurrent_per_host=2)
    url = "https://boards-api.greenhouse.io/v1/boards/a"
    active = 0
    peak = 0
    guard = threading.Lock()
    worker_count = 6
    start = threading.Barrier(worker_count)

    def worker() -> None:
        nonlocal active, peak
        # All workers line up first so they contend for the host slot simultaneously.
        start.wait(timeout=5)
        with limiter.hold(url):
            with guard:
                active += 1
                peak = max(peak, active)
            # Give other threads a chance to pile in if the cap is not enforced.
            threading.Event().wait(0.02)
            with guard:
                active -= 1

    threads = [threading.Thread(target=worker) for _ in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert peak <= 2, f"observed {peak} concurrent requests against a cap of 2"
    assert peak > 0, "workers never ran"


def test_concurrent_pacing_does_not_double_book_a_slot() -> None:
    """Threads must queue behind each other, not all compute the same send time."""
    clock = FakeClock()
    limiter = _limiter(clock, min_interval_seconds=1.0)
    reserved: list[float] = []
    guard = threading.Lock()
    url = "https://boards-api.greenhouse.io/a"

    def worker() -> None:
        # Deliberately not merged into one `with`: the guard must be taken *inside* the
        # host slot, so it only protects the list append and never the limiter wait.
        with limiter.hold(url):  # noqa: SIM117
            with guard:
                reserved.append(clock.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(reserved) == 4
    assert len(set(reserved)) == len(reserved), (
        f"two requests were scheduled for the same instant: {reserved}"
    )


def test_policy_rejects_negative_limits() -> None:
    with pytest.raises(ValueError, match="min_interval_seconds cannot be negative"):
        HttpPolicy(min_interval_seconds=-1)
    with pytest.raises(ValueError, match="max_concurrent_per_host cannot be negative"):
        HttpPolicy(max_concurrent_per_host=-1)


def test_client_paces_requests_using_its_policy() -> None:
    """The limiter reaches every adapter through the client, not adapter by adapter."""

    class _Transport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(self, url: str, **_: object) -> object:
            self.calls.append(url)
            raise AssertionError("transport should not be reached in this test")

    delays: list[float] = []
    client = BoundedHttpClient(
        policy=HttpPolicy(min_interval_seconds=3.0),
        transport=_Transport(),
        sleep=delays.append,
    )

    assert client.policy.min_interval_seconds == 3.0
    # A shared limiter can be injected so one instance spans the whole scan.
    shared = HostRateLimiter(min_interval_seconds=0.5)
    paced = BoundedHttpClient(transport=_Transport(), rate_limiter=shared)
    assert paced._rate_limiter is shared
