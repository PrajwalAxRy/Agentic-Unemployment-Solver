"""Job lifecycle state machine: absence, probing, and expiry.

Implements ``to_change.md`` 3.2 and 3.3. The design rule underneath all of it:

    **Never expire on failure.** A job disappearing because we could not look is not the
    same as a job disappearing because it was taken down, and the system must not be able
    to confuse the two.

That matters because the cost is asymmetric. Closing a live job removes it from the feed
silently -- nobody sees the job that is not there. Keeping a dead job costs one wasted
click. So every ambiguous signal resolves toward keeping the job open.

Three guards stack (3.3), and each one blocks a different failure:

1. **Absences only count when the company's scan succeeded**, and on failure the counter
   *freezes* rather than resetting. Freezing matters: resetting would let a source that
   fails every other day keep a dead job alive forever, while freezing simply declines to
   count days we did not observe.
2. **A sharp single-run drop in a company's listing count marks the run untrusted** and
   excludes it from expiry entirely. This is the guard against the catastrophic case --
   the board that returns 50 of 200 jobs with no error.
3. **A job needs at least two confirmed sightings before it is eligible to expire.** A job
   seen exactly once may have been a transient glitch in the source rather than a real
   posting, and expiring it would be acting on a single observation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from job_finder.core.job_probe import JobProbeResult, ProbeVerdict

_LOGGER = logging.getLogger(__name__)

DEFAULT_ABSENCE_THRESHOLD = 3
"""Consecutive absences that close a job (3.2, revised down from 5).

Gated on the 5.1 dry-run demonstrating that the probe fires on first absence. If it does
not, revert to 5 until it does -- 10.F is explicit that the real question was never "3 or
5" but "does the probe reliably run".
"""

DEFAULT_LIVE_BUT_MISSING_DAYS = 3
"""Days a live-but-missing job is held before closing (3.2).

A separate clock from plain absence, because the URL resolving is genuine evidence that
the posting still exists -- search-index lag behind a live page is normal on Workday and
Oracle (5.3).
"""

MINIMUM_SIGHTINGS_TO_EXPIRE = 2
"""Guard 3: a job seen only once is not eligible to expire."""

COLLAPSE_RATIO = 0.5
"""A run returning less than this fraction of the previous count is untrusted (guard 2)."""

COLLAPSE_MINIMUM_BASELINE = 10
"""Below this many previously-seen jobs, ratios are too noisy to judge."""


class JobStatus(StrEnum):
    """Lifecycle status stored per job (4.1)."""

    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class JobLifecycleState:
    """Current lifecycle state for one job. Stored as state, not history (4.2)."""

    status: JobStatus = JobStatus.ACTIVE
    consecutive_absences: int = 0
    sighting_count: int = 0
    live_but_missing_days: int = 0
    probe_state: str | None = None
    closed_at: date | None = None
    last_seen: date | None = None

    @property
    def eligible_to_expire(self) -> bool:
        """Guard 3 (3.3): at least two confirmed sightings."""
        return self.sighting_count >= MINIMUM_SIGHTINGS_TO_EXPIRE


@dataclass(frozen=True, slots=True)
class CompanyRunContext:
    """What this run knows about the company the job belongs to.

    The lifecycle decision is not a property of the job alone. Whether an absence means
    anything depends entirely on whether the run that failed to see it was trustworthy.
    """

    scan_succeeded: bool
    """Guard 1 (3.3): on failure, counters freeze."""

    listing_complete: bool
    """Whether pagination was provably exhausted (3.4).

    This is ``AdapterResult.safe_for_absence_counting`` -- true only for ``EXHAUSTED``. A
    page cap or truncation means "not fetched", not "not there".
    """

    current_listing_count: int = 0
    previous_listing_count: int | None = None

    @property
    def listing_count_collapsed(self) -> bool:
        """Guard 2 (3.3): a sharp single-run drop marks the run untrusted."""
        if self.previous_listing_count is None:
            return False
        if self.previous_listing_count < COLLAPSE_MINIMUM_BASELINE:
            return False
        return self.current_listing_count < self.previous_listing_count * COLLAPSE_RATIO

    @property
    def trustworthy_for_expiry(self) -> bool:
        """Whether absence observed in this run may advance any counter at all."""
        return self.scan_succeeded and self.listing_complete and not self.listing_count_collapsed


def record_sighting(state: JobLifecycleState, *, today: date) -> JobLifecycleState:
    """Record that the job was present in the listing.

    Clears every absence clock. A job that came back was never really gone, and 5.3 is
    explicit that reappearance is not inherently an error -- recruiter unpublish and
    republish, board freshness rotation, and search-index lag all produce it legitimately.
    """
    return replace(
        state,
        status=JobStatus.ACTIVE,
        consecutive_absences=0,
        live_but_missing_days=0,
        sighting_count=state.sighting_count + 1,
        probe_state=None,
        closed_at=None,
        last_seen=today,
    )


def record_absence(
    state: JobLifecycleState,
    *,
    context: CompanyRunContext,
    probe: JobProbeResult | None,
    today: date,
    absence_threshold: int = DEFAULT_ABSENCE_THRESHOLD,
    live_but_missing_days: int = DEFAULT_LIVE_BUT_MISSING_DAYS,
) -> JobLifecycleState:
    """Record that the job was absent from the listing, and decide what that means.

    ``probe`` is the result of probing the job URL, or ``None`` if no probe ran. Passing
    ``None`` on a first absence is a bug in the caller rather than a supported mode: 3.2
    requires the probe to fire on first absence, and at a 3-absence threshold it is the
    only thing standing between a silently truncated listing and a closed live job.
    """
    if not context.trustworthy_for_expiry:
        # Guard 1 and 2: freeze, do not reset. Freezing declines to count a day we did not
        # really observe; resetting would let a flaky source keep a dead job alive forever.
        _LOGGER.info(
            "lifecycle_frozen reason=%s absences=%d",
            _untrusted_reason(context),
            state.consecutive_absences,
        )
        return state

    if probe is not None and not probe.advances_state:
        # Timeout / 429 / 5xx: no information. Advance nothing (3.2).
        _LOGGER.info("lifecycle_frozen reason=probe_no_information code=%s", probe.reason_code)
        return replace(state, probe_state=probe.reason_code)

    if probe is not None and probe.verdict is ProbeVerdict.CLOSED:
        # Definitive. Close immediately without waiting out the absence counter, but the
        # two-sighting guard still applies -- a job seen once and then 404ing was probably
        # never really there.
        if not state.eligible_to_expire:
            _LOGGER.info(
                "lifecycle_close_withheld reason=insufficient_sightings count=%d",
                state.sighting_count,
            )
            return replace(state, probe_state=probe.reason_code)
        return replace(
            state,
            status=JobStatus.CLOSED,
            probe_state=probe.reason_code,
            closed_at=today,
            consecutive_absences=state.consecutive_absences + 1,
        )

    if probe is not None and probe.verdict is ProbeVerdict.LIVE_BUT_MISSING:
        # The URL resolves. Runs on its own slower clock, and crucially does not advance
        # the plain-absence counter -- that is the whole point of the branch.
        elapsed = state.live_but_missing_days + 1
        updated = replace(state, live_but_missing_days=elapsed, probe_state=probe.reason_code)
        if elapsed >= live_but_missing_days and state.eligible_to_expire:
            return replace(updated, status=JobStatus.CLOSED, closed_at=today)
        return updated

    if probe is not None and probe.verdict is ProbeVerdict.LIVE:
        # Probed live and listed: not actually absent. Nothing to advance.
        return replace(state, probe_state=probe.reason_code)

    absences = state.consecutive_absences + 1
    updated = replace(
        state,
        consecutive_absences=absences,
        probe_state=probe.reason_code if probe is not None else None,
    )
    if absences >= absence_threshold and state.eligible_to_expire:
        return replace(updated, status=JobStatus.CLOSED, closed_at=today)
    return updated


def days_active(state: JobLifecycleState, first_seen: date) -> int | None:
    """``last_seen - first_seen`` (4.2a). Computed, never stored.

    4.2a also fixes the display rule: show ``last_seen`` as the closing date, not
    ``closed_at``. ``closed_at`` lags by up to the absence threshold, so showing it beside
    a ``last_seen``-derived duration would put two disagreeing numbers on screen.
    ``closed_at`` remains stored as an operational record of when detection happened.
    """
    if state.last_seen is None:
        return None
    return (state.last_seen - first_seen).days


def _untrusted_reason(context: CompanyRunContext) -> str:
    if not context.scan_succeeded:
        return "scan_failed"
    if not context.listing_complete:
        return "listing_incomplete"
    return "listing_count_collapsed"
