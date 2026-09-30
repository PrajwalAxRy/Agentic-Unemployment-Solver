"""Waiting out a network outage instead of failing the whole scan.

The failure this prevents: a 40-minute scan loses Wi-Fi at minute ten, and because
HttpPolicy's retry budget is about 1.5 seconds, the remaining 140 companies all fail
within a couple of minutes. The run is wasted and has to be repeated.

The risk it introduces is the opposite one -- pausing a healthy scan because one site is
unreachable. Most of these tests are about that boundary.
"""

from __future__ import annotations

import pytest

from job_finder.adapters.connectivity import (
    ConnectivityPolicy,
    ConnectivityWaiter,
    is_network_available,
)


def _waiter(
    *,
    up_after: int | None = None,
    max_wait_seconds: float = 600.0,
    threshold: int = 3,
) -> tuple[ConnectivityWaiter, list[float]]:
    """A waiter whose network returns after ``up_after`` checks (None = never)."""
    slept: list[float] = []
    checks = {"count": 0}

    def check() -> bool:
        checks["count"] += 1
        return up_after is not None and checks["count"] > up_after

    return (
        ConnectivityWaiter(
            policy=ConnectivityPolicy(
                poll_interval_seconds=120.0,
                max_wait_seconds=max_wait_seconds,
                consecutive_failures_before_waiting=threshold,
            ),
            sleep=slept.append,
            check=check,
        ),
        slept,
    )


def test_a_single_network_failure_does_not_trigger_waiting() -> None:
    """One unreachable host is far more likely than a dropped connection.

    Pausing the whole scan for that would be worse than the failure it avoids.
    """
    waiter, _ = _waiter(up_after=0)

    assert waiter.record_network_failure() is False
    assert waiter.record_network_failure() is False


def test_consecutive_failures_suspect_an_outage() -> None:
    waiter, _ = _waiter(up_after=0)

    waiter.record_network_failure()
    waiter.record_network_failure()

    assert waiter.record_network_failure() is True


def test_a_success_resets_the_suspicion() -> None:
    """An intermittently bad host must never accumulate into a false outage."""
    waiter, _ = _waiter(up_after=0)

    waiter.record_network_failure()
    waiter.record_network_failure()
    waiter.record_success()

    assert waiter.record_network_failure() is False


def test_waiting_returns_immediately_when_the_network_is_actually_up() -> None:
    """Three failures against three different dead hosts is not an outage."""
    waiter, slept = _waiter(up_after=0)

    assert waiter.wait_for_network() is True
    assert slept == [], "must not sleep when connectivity is already fine"


def test_waiting_polls_until_the_network_returns() -> None:
    waiter, slept = _waiter(up_after=3)

    assert waiter.wait_for_network() is True
    # One check before the loop, then three polls before it comes back.
    assert slept == [120.0, 120.0, 120.0]
    assert waiter.total_waits == 1


def test_waiting_gives_up_after_the_budget_and_says_so() -> None:
    """Bounded on purpose: a scan on a permanently disconnected machine must exit."""
    waiter, slept = _waiter(up_after=None, max_wait_seconds=600.0)

    assert waiter.wait_for_network() is False
    assert len(slept) == 5, "600s budget at 120s per poll"


def test_the_failure_counter_resets_after_the_network_returns() -> None:
    waiter, _ = _waiter(up_after=1)
    waiter.record_network_failure()
    waiter.record_network_failure()
    waiter.record_network_failure()

    waiter.wait_for_network()

    assert waiter.consecutive_failures == 0
    assert waiter.record_network_failure() is False


def test_waiting_can_be_disabled() -> None:
    waiter = ConnectivityWaiter(
        policy=ConnectivityPolicy(enabled=False),
        sleep=lambda _: pytest.fail("must not sleep when disabled"),
        check=lambda: pytest.fail("must not probe when disabled"),  # type: ignore[arg-type,return-value]
    )

    assert waiter.wait_for_network() is False


def test_snapshot_reports_time_actually_lost() -> None:
    waiter, _ = _waiter(up_after=2)

    waiter.wait_for_network()

    assert waiter.snapshot() == {"outages_detected": 1, "total_waited_seconds": 240.0}


@pytest.mark.parametrize(
    ("poll", "maximum", "threshold"),
    [(0, 600, 3), (-1, 600, 3), (120, -1, 3), (120, 600, 0)],
)
def test_invalid_policy_is_rejected(poll: float, maximum: float, threshold: int) -> None:
    with pytest.raises(ValueError):
        ConnectivityPolicy(
            poll_interval_seconds=poll,
            max_wait_seconds=maximum,
            consecutive_failures_before_waiting=threshold,
        )


def test_probe_reports_false_when_every_target_is_unreachable() -> None:
    """Uses a reserved-for-documentation address that cannot route anywhere."""
    assert is_network_available(timeout_seconds=0.2, targets=(("192.0.2.1", 9),)) is False
