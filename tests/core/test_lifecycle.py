"""Job lifecycle state machine (to_change.md 3.2, 3.3, 4.2a).

The asymmetry that drives every assertion here: closing a live job removes it from the
feed silently -- nobody sees the job that is not there -- while keeping a dead job costs
one wasted click. So every ambiguous signal must resolve toward keeping the job open.

3.4 already happened once for real: the first 2026-09-29 run hit a transient Workday
problem, and targeted verification then returned 378 jobs across 19 pages. Under automated
expiry that partial run could have closed live jobs. These tests are what stop that.
"""

from __future__ import annotations

from datetime import date

import pytest

from job_finder.core.job_probe import JobProbeResult, ProbeVerdict
from job_finder.core.lifecycle import (
    DEFAULT_ABSENCE_THRESHOLD,
    CompanyRunContext,
    JobLifecycleState,
    JobStatus,
    days_active,
    record_absence,
    record_sighting,
)

TODAY = date(2026, 9, 30)


def _trusted(**overrides: object) -> CompanyRunContext:
    values: dict[str, object] = {
        "scan_succeeded": True,
        "listing_complete": True,
        "current_listing_count": 100,
        "previous_listing_count": 100,
    }
    values.update(overrides)
    return CompanyRunContext(**values)  # type: ignore[arg-type]


def _probe(verdict: ProbeVerdict, reason: str = "test") -> JobProbeResult:
    return JobProbeResult(
        verdict=verdict,
        reason_code=reason,
        status_code=200,
        final_url=None,
        detail="",
    )


def _established(sightings: int = 5) -> JobLifecycleState:
    """A job with enough history to be eligible to expire."""
    return JobLifecycleState(sighting_count=sightings, last_seen=date(2026, 9, 29))


def test_three_consecutive_absences_close_a_job() -> None:
    state = _established()
    for _ in range(DEFAULT_ABSENCE_THRESHOLD - 1):
        state = record_absence(
            state, context=_trusted(), probe=_probe(ProbeVerdict.LIVE_BUT_MISSING), today=TODAY
        )
        assert state.status is JobStatus.ACTIVE

    # Plain absence, no probe evidence keeping it alive.
    state = JobLifecycleState(sighting_count=5, consecutive_absences=2)
    state = record_absence(state, context=_trusted(), probe=None, today=TODAY)

    assert state.consecutive_absences == 3
    assert state.status is JobStatus.CLOSED
    assert state.closed_at == TODAY


def test_a_sighting_clears_every_absence_clock() -> None:
    """Reappearance is not inherently an error (5.3)."""
    state = JobLifecycleState(sighting_count=3, consecutive_absences=2, live_but_missing_days=2)

    state = record_sighting(state, today=TODAY)

    assert state.consecutive_absences == 0
    assert state.live_but_missing_days == 0
    assert state.status is JobStatus.ACTIVE
    assert state.last_seen == TODAY
    assert state.sighting_count == 4


# ---------------------------------------------------------------------------
# Guard 1 (3.3): absences only count when the scan succeeded
# ---------------------------------------------------------------------------


def test_failed_scan_freezes_rather_than_resets_the_counter() -> None:
    """Freezing, not resetting -- the distinction matters.

    Resetting would let a source that fails every other day keep a dead job alive
    forever. Freezing simply declines to count a day we did not observe.
    """
    state = JobLifecycleState(sighting_count=5, consecutive_absences=2)

    after = record_absence(state, context=_trusted(scan_succeeded=False), probe=None, today=TODAY)

    assert after.consecutive_absences == 2, "counter must freeze, not reset and not advance"
    assert after.status is JobStatus.ACTIVE


def test_incomplete_listing_never_advances_the_counter() -> None:
    """3.4 via 6.6: only an EXHAUSTED run may feed the absence counter.

    A page cap or truncation means 'not fetched', not 'not there'. This is the link
    between the CompletionReason enum and the expiry logic -- without it, silent
    truncation is indistinguishable from a shrinking board.
    """
    state = JobLifecycleState(sighting_count=5, consecutive_absences=2)

    after = record_absence(state, context=_trusted(listing_complete=False), probe=None, today=TODAY)

    assert after.consecutive_absences == 2
    assert after.status is JobStatus.ACTIVE


# ---------------------------------------------------------------------------
# Guard 2 (3.3): a collapsed listing count marks the run untrusted
# ---------------------------------------------------------------------------


def test_collapsed_listing_count_excludes_the_run_from_expiry() -> None:
    """The catastrophic case: a board returns 50 of 200 jobs with no error."""
    context = _trusted(current_listing_count=50, previous_listing_count=200)
    assert context.listing_count_collapsed is True
    assert context.trustworthy_for_expiry is False

    state = JobLifecycleState(sighting_count=5, consecutive_absences=2)
    after = record_absence(state, context=context, probe=None, today=TODAY)

    assert after.status is JobStatus.ACTIVE
    assert after.consecutive_absences == 2


def test_small_boards_do_not_trigger_the_collapse_guard() -> None:
    """Below a floor, ratios are noise -- 4 jobs down from 9 is an ordinary Tuesday."""
    context = _trusted(current_listing_count=4, previous_listing_count=9)

    assert context.listing_count_collapsed is False
    assert context.trustworthy_for_expiry is True


def test_a_modest_decline_is_not_a_collapse() -> None:
    context = _trusted(current_listing_count=85, previous_listing_count=100)

    assert context.listing_count_collapsed is False


# ---------------------------------------------------------------------------
# Guard 3 (3.3): >= 2 confirmed sightings before expiry
# ---------------------------------------------------------------------------


def test_a_job_seen_once_cannot_expire_on_absence() -> None:
    state = JobLifecycleState(sighting_count=1, consecutive_absences=2)

    after = record_absence(state, context=_trusted(), probe=None, today=TODAY)

    assert after.consecutive_absences == 3
    assert after.status is JobStatus.ACTIVE, "one sighting may have been a source glitch"


def test_a_job_seen_once_cannot_be_closed_even_by_a_404() -> None:
    """The strongest possible signal still defers to the sightings guard."""
    state = JobLifecycleState(sighting_count=1)

    after = record_absence(
        state, context=_trusted(), probe=_probe(ProbeVerdict.CLOSED, "http_gone"), today=TODAY
    )

    assert after.status is JobStatus.ACTIVE
    assert after.probe_state == "http_gone"


# ---------------------------------------------------------------------------
# Probe verdicts (3.2)
# ---------------------------------------------------------------------------


def test_a_definitive_closure_closes_immediately() -> None:
    """404/410 does not wait out the absence counter."""
    state = _established()

    after = record_absence(
        state, context=_trusted(), probe=_probe(ProbeVerdict.CLOSED, "http_gone"), today=TODAY
    )

    assert after.status is JobStatus.CLOSED
    assert after.closed_at == TODAY


def test_no_information_advances_nothing() -> None:
    """Timeout / 429 / 5xx are statements about the server, not about the job."""
    state = JobLifecycleState(sighting_count=5, consecutive_absences=2, live_but_missing_days=1)

    after = record_absence(
        state,
        context=_trusted(),
        probe=_probe(ProbeVerdict.NO_INFORMATION, "probe_timeout"),
        today=TODAY,
    )

    assert after.consecutive_absences == 2
    assert after.live_but_missing_days == 1
    assert after.status is JobStatus.ACTIVE


def test_live_but_missing_runs_on_its_own_slower_clock() -> None:
    """The branch that makes a 3-absence threshold survivable (10.F).

    A live URL routes here instead of closing, and critically does not advance the plain
    absence counter -- that separation is the entire safety margin.
    """
    state = _established()

    for day in range(1, 3):
        state = record_absence(
            state, context=_trusted(), probe=_probe(ProbeVerdict.LIVE_BUT_MISSING), today=TODAY
        )
        assert state.status is JobStatus.ACTIVE, f"closed too early on day {day}"
        assert state.consecutive_absences == 0, "must not advance the plain-absence counter"
        assert state.live_but_missing_days == day

    state = record_absence(
        state, context=_trusted(), probe=_probe(ProbeVerdict.LIVE_BUT_MISSING), today=TODAY
    )

    assert state.live_but_missing_days == 3
    assert state.status is JobStatus.CLOSED


def test_a_live_and_listed_probe_advances_nothing() -> None:
    state = JobLifecycleState(sighting_count=5, consecutive_absences=1)

    after = record_absence(state, context=_trusted(), probe=_probe(ProbeVerdict.LIVE), today=TODAY)

    assert after.consecutive_absences == 1
    assert after.status is JobStatus.ACTIVE


# ---------------------------------------------------------------------------
# 4.2a: days active
# ---------------------------------------------------------------------------


def test_days_active_is_computed_from_last_seen() -> None:
    """4.2a: last_seen - first_seen, computed rather than stored.

    closed_at lags by up to the absence threshold, so a duration derived from it would
    disagree with the displayed closing date. One date drives both.
    """
    state = JobLifecycleState(sighting_count=5, last_seen=date(2026, 9, 29))

    assert days_active(state, first_seen=date(2026, 9, 1)) == 28


def test_days_active_is_unknown_without_a_sighting() -> None:
    assert days_active(JobLifecycleState(), first_seen=date(2026, 9, 1)) is None


@pytest.mark.parametrize(
    ("scan_succeeded", "listing_complete", "expected"),
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
        (False, False, False),
    ],
)
def test_trustworthiness_requires_every_condition(
    scan_succeeded: bool, listing_complete: bool, expected: bool
) -> None:
    context = _trusted(scan_succeeded=scan_succeeded, listing_complete=listing_complete)

    assert context.trustworthy_for_expiry is expected
