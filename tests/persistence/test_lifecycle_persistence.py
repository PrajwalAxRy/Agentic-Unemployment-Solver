"""Lifecycle state survives a round trip through the database (to_change.md 4.1, 4.2).

The unit tests for the state machine work on in-memory dataclasses. These drive the real
repository, because the machine is only useful if tomorrow's run can read today's counters
-- 4.2 keeps ``consecutive_absences`` and ``probe_state`` as stored *state* precisely
because the state machine depends on them across runs.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.job_probe import JobProbeResult, ProbeVerdict
from job_finder.core.lifecycle import (
    CompanyRunContext,
    JobLifecycleState,
    JobStatus,
    record_absence,
    record_sighting,
)
from job_finder.persistence.database import migrated_database
from job_finder.persistence.repository import JobStateRepository


def _job(index: int = 1) -> NormalizedJob:
    return NormalizedJob(
        1,
        "acme",
        "greenhouse",
        str(index),
        "Machine Learning Engineer",
        "machine learning engineer",
        "Bengaluru, India",
        ("bengaluru india",),
        None,
        None,
        DateBasis.UNKNOWN,
        f"https://jobs.acme.com/{index}",
    )


def _context(**overrides: object) -> CompanyRunContext:
    values: dict[str, object] = {
        "scan_succeeded": True,
        "listing_complete": True,
        "current_listing_count": 100,
        "previous_listing_count": 100,
    }
    values.update(overrides)
    return CompanyRunContext(**values)  # type: ignore[arg-type]


@pytest.fixture
def repository():
    path = Path(tempfile.mkdtemp()) / "jobs.sqlite3"
    with migrated_database(path) as connection:
        yield JobStateRepository(connection)


def test_lifecycle_state_round_trips(repository: JobStateRepository) -> None:
    observation = repository.observe_listing(
        _job(), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
    )
    key = observation.record.job_key

    state = record_sighting(JobLifecycleState(), today=date(2026, 9, 25))
    repository.record_lifecycle(key, state)

    stored = repository.require(key)
    assert stored.status == "active"
    assert stored.sighting_count == 1
    assert stored.consecutive_absences == 0


def test_absence_counters_persist_so_tomorrow_can_read_today(
    repository: JobStateRepository,
) -> None:
    """The reason 4.2 stores these as state rather than deriving them."""
    observation = repository.observe_listing(
        _job(), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
    )
    key = observation.record.job_key

    state = JobLifecycleState()
    for day in (25, 26):
        state = record_sighting(state, today=date(2026, 9, day))
        repository.record_lifecycle(key, state)

    # Day 27: absent, no probe evidence.
    state = record_absence(state, context=_context(), probe=None, today=date(2026, 9, 27))
    repository.record_lifecycle(key, state)

    reloaded = repository.require(key)
    assert reloaded.consecutive_absences == 1
    assert reloaded.status == "active"

    # A fresh state built purely from storage must continue the sequence correctly.
    resumed = JobLifecycleState(
        status=JobStatus(reloaded.status),
        consecutive_absences=reloaded.consecutive_absences,
        sighting_count=reloaded.sighting_count,
        live_but_missing_days=reloaded.live_but_missing_days,
        probe_state=reloaded.probe_state,
        closed_at=reloaded.closed_at,
        last_seen=reloaded.last_seen_at.date(),
    )
    for day in (28, 29):
        resumed = record_absence(resumed, context=_context(), probe=None, today=date(2026, 9, day))
        repository.record_lifecycle(key, resumed)

    final = repository.require(key)
    assert final.consecutive_absences == 3
    assert final.status == "closed"
    assert final.closed_at == date(2026, 9, 29)


def test_live_but_missing_runs_its_own_clock_in_storage(
    repository: JobStateRepository,
) -> None:
    observation = repository.observe_listing(
        _job(), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
    )
    key = observation.record.job_key

    state = JobLifecycleState()
    for day in (25, 26):
        state = record_sighting(state, today=date(2026, 9, day))
    repository.record_lifecycle(key, state)

    probe = JobProbeResult(
        ProbeVerdict.LIVE_BUT_MISSING, "live_but_absent_from_listing", 200, None, ""
    )
    for day, expected in ((27, 1), (28, 2)):
        state = record_absence(state, context=_context(), probe=probe, today=date(2026, 9, day))
        repository.record_lifecycle(key, state)
        stored = repository.require(key)
        assert stored.live_but_missing_days == expected
        assert stored.consecutive_absences == 0, "must not advance the plain-absence counter"
        assert stored.status == "active"

    state = record_absence(state, context=_context(), probe=probe, today=date(2026, 9, 29))
    repository.record_lifecycle(key, state)
    assert repository.require(key).status == "closed"


def test_verdict_at_is_set_once(repository: JobStateRepository) -> None:
    """3.6: the feed sorts on verdict_at, so it must not drift forward on re-evaluation.

    Rows recovered from the normalization bug carry old first_seen_at values. Keying the
    feed on first sighting would mean the ~78 Google roles never appear as new; keying it
    on a verdict_at that kept moving would be just as wrong in the other direction.
    """
    observation = repository.observe_listing(
        _job(), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
    )
    key = observation.record.job_key

    repository.record_verdict(
        key,
        verdict="substantive",
        verdict_at=datetime(2026, 9, 26, tzinfo=UTC),
        required_experience="3+ years",
    )
    repository.record_verdict(
        key, verdict="substantive", verdict_at=datetime(2026, 9, 29, tzinfo=UTC)
    )

    stored = repository.require(key)
    assert stored.verdict_at is not None
    assert stored.verdict_at.date() == date(2026, 9, 26)
    assert stored.required_experience == "3+ years", "must not be cleared by a later write"


def test_verdict_evidence_is_persisted(repository: JobStateRepository) -> None:
    """Migration 5: the quote behind a verdict, which used to be thrown away."""
    observation = repository.observe_listing(
        _job(), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
    )
    key = observation.record.job_key

    repository.record_verdict(
        key,
        verdict="unrelated",
        verdict_at=datetime(2026, 9, 26, tzinfo=UTC),
        relevance_evidence="maintain Salesforce dashboards",
        relevance_reason="Business analytics, not ML engineering.",
        location_evidence="Remote (US only)",
        location_reason="Explicitly excludes India.",
    )

    stored = repository.require(key)
    assert stored.relevance_evidence == "maintain Salesforce dashboards"
    assert stored.relevance_reason == "Business analytics, not ML engineering."
    assert stored.location_evidence == "Remote (US only)"
    assert stored.location_reason == "Explicitly excludes India."


def test_a_later_verdict_without_location_evidence_keeps_the_stored_pair(
    repository: JobStateRepository,
) -> None:
    """The model is asked about location only when the filter could not resolve it.

    So a second run that resolves it deterministically passes None here. That means "not
    asked this time", not "no longer true", and must not erase a stored judgment.
    """
    observation = repository.observe_listing(
        _job(), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
    )
    key = observation.record.job_key

    repository.record_verdict(
        key,
        verdict="peripheral",
        verdict_at=datetime(2026, 9, 26, tzinfo=UTC),
        relevance_evidence="some ML exposure",
        relevance_reason="Adjacent, not core.",
        location_evidence="Remote (India eligible)",
        location_reason="India is listed.",
    )
    repository.record_verdict(
        key,
        verdict="substantive",
        verdict_at=datetime(2026, 9, 29, tzinfo=UTC),
        relevance_evidence="train and deploy models",
        relevance_reason="Core ML work.",
    )

    stored = repository.require(key)
    # The verdict itself overwrites -- a re-judgment supersedes.
    assert stored.verdict == "substantive"
    assert stored.relevance_evidence == "train and deploy models"
    assert stored.location_evidence == "Remote (India eligible)", "must survive a silent run"
    assert stored.location_reason == "India is listed."


def test_active_jobs_query_excludes_closed_rows(repository: JobStateRepository) -> None:
    """Absence detection iterates open jobs; closed ones must drop out."""
    for index in (1, 2):
        repository.observe_listing(
            _job(index), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
        )
    assert len(repository.active_jobs_for_company("acme")) == 2

    first = repository.active_jobs_for_company("acme")[0]
    repository.record_lifecycle(
        first.job_key,
        JobLifecycleState(status=JobStatus.CLOSED, sighting_count=2, closed_at=date(2026, 9, 29)),
    )

    remaining = repository.active_jobs_for_company("acme")
    assert len(remaining) == 1
    assert remaining[0].job_key != first.job_key


def test_untrusted_run_writes_no_change(repository: JobStateRepository) -> None:
    """Guard 1 and 2 at the storage boundary: a frozen counter must stay frozen."""
    observation = repository.observe_listing(
        _job(), observed_at=datetime(2026, 9, 25, tzinfo=UTC), profile_version="1.0"
    )
    key = observation.record.job_key
    state = JobLifecycleState(sighting_count=5, consecutive_absences=2)
    repository.record_lifecycle(key, state)

    frozen = record_absence(
        state, context=_context(scan_succeeded=False), probe=None, today=date(2026, 9, 27)
    )
    repository.record_lifecycle(key, frozen)

    stored = repository.require(key)
    assert stored.consecutive_absences == 2
    assert stored.status == "active"
