"""Wait for network connectivity to return instead of failing a whole scan.

A dropped connection and a flaky request look identical at the transport layer, but the
right response to each is opposite. ``HttpPolicy`` already retries a failed request twice
over about 1.5 seconds, which is correct for a flaky request. For a dropped connection it
is useless: the retries fail just as fast, the company is marked ``FAILED``, and the scan
races through every remaining company doing the same. A 40-minute scan that loses Wi-Fi at
minute ten produces 140 source failures in a couple of minutes and has to be re-run.

The distinguishing signal is **consecutiveness**. One network error is a bad request; the
same error against several different hosts in a row means the machine is offline. This
module waits for that second case, and only that case.

What it deliberately does not do:

* **It does not retry the request.** It only answers "is the network back yet". The caller
  retries, so the existing retry budget, rate limiting and ``Retry-After`` handling all
  still apply unchanged.
* **It does not treat an HTTP error as an outage.** A 500 or a 429 means the server is
  reachable and unhappy, which is a completely different problem with a completely
  different remedy.
* **It does not close anything.** Jobs missed during an outage sit behind a ``TRUNCATED``
  completion reason, so :attr:`safe_for_absence_counting` already stops them feeding the
  absence counter (``to_change.md`` 3.4). Waiting is about not wasting the run, not about
  data safety -- that guard is independent and stays in force.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 120.0
"""Two minutes between checks -- frequent enough to resume promptly, sparse enough that
an hour of downtime costs 30 log lines rather than thousands."""

DEFAULT_MAX_WAIT_SECONDS = 7200.0
"""Two hours. Long enough to ride out a real outage; bounded so a scan left running on a
permanently disconnected machine eventually exits with a reason instead of hanging."""

_PROBE_TARGETS: tuple[tuple[str, int], ...] = (
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
)
"""Public DNS resolvers, checked by raw TCP.

Deliberately not an HTTP request to a job board: that would conflate "the internet is
back" with "this particular site is up", and a site-specific outage must not hold the
whole scan. Deliberately not a DNS *lookup* either, since a cached or hijacked resolver
can answer while the connection is dead.
"""


@dataclass(frozen=True, slots=True)
class ConnectivityPolicy:
    """How long, and how often, to wait for the network to return."""

    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS
    consecutive_failures_before_waiting: int = 3
    """Network errors in a row before concluding the machine is offline.

    Three rather than one: a single failure is far more likely to be one unreachable host
    than a dropped connection, and pausing the entire scan for that would be worse than
    the failure it is trying to avoid.
    """

    enabled: bool = True

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.max_wait_seconds < 0:
            raise ValueError("max_wait_seconds cannot be negative")
        if self.consecutive_failures_before_waiting < 1:
            raise ValueError("consecutive_failures_before_waiting must be at least 1")

    @property
    def max_attempts(self) -> int:
        return int(self.max_wait_seconds // self.poll_interval_seconds)


def is_network_available(
    *,
    timeout_seconds: float = 5.0,
    targets: Sequence[tuple[str, int]] = _PROBE_TARGETS,
) -> bool:
    """Whether a TCP connection can be opened to any known-good host."""
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            continue
    return False


@dataclass(slots=True)
class ConnectivityWaiter:
    """Tracks consecutive network failures and blocks until the network returns.

    Stateful because the decision depends on history: the same exception is routine once
    and significant three times running. Any success resets the count, so an intermittent
    bad host never accumulates into a false outage.
    """

    policy: ConnectivityPolicy = ConnectivityPolicy()
    sleep: Callable[[float], None] = time.sleep
    check: Callable[[], bool] = is_network_available
    consecutive_failures: int = 0
    total_waits: int = 0
    total_waited_seconds: float = 0.0

    def record_success(self) -> None:
        """Note that a request succeeded. Clears the outage suspicion."""
        self.consecutive_failures = 0

    def record_network_failure(self) -> bool:
        """Note a network-level failure. Returns whether an outage is now suspected."""
        self.consecutive_failures += 1
        return self.consecutive_failures >= self.policy.consecutive_failures_before_waiting

    def wait_for_network(self, *, context: str = "") -> bool:
        """Block until the network returns, or the wait budget is exhausted.

        Returns ``True`` if connectivity came back (the caller should retry) and ``False``
        if it did not (the caller should fail normally). Returning a bool rather than
        raising keeps the decision with the caller, which already knows how to record a
        failed company.
        """
        if not self.policy.enabled:
            return False

        label = f" {context}" if context else ""
        if self.check():
            # Already back, or the failures were host-specific rather than an outage.
            self.consecutive_failures = 0
            return True

        _LOGGER.warning(
            "network_unavailable%s consecutive_failures=%d polling every %.0fs for up to %.0fm",
            label,
            self.consecutive_failures,
            self.policy.poll_interval_seconds,
            self.policy.max_wait_seconds / 60,
        )
        self.total_waits += 1

        for attempt in range(1, self.policy.max_attempts + 1):
            self.sleep(self.policy.poll_interval_seconds)
            self.total_waited_seconds += self.policy.poll_interval_seconds
            if self.check():
                _LOGGER.warning(
                    "network_restored after %.0fs (%d checks); resuming",
                    attempt * self.policy.poll_interval_seconds,
                    attempt,
                )
                self.consecutive_failures = 0
                return True
            _LOGGER.info(
                "network_still_down check=%d/%d elapsed=%.0fm",
                attempt,
                self.policy.max_attempts,
                attempt * self.policy.poll_interval_seconds / 60,
            )

        _LOGGER.error(
            "network_wait_exhausted after %.0fm; continuing with failures recorded",
            self.policy.max_wait_seconds / 60,
        )
        return False

    def snapshot(self) -> dict[str, object]:
        """Waiting that happened during a run, for the scan report."""
        return {
            "outages_detected": self.total_waits,
            "total_waited_seconds": round(self.total_waited_seconds, 1),
        }
