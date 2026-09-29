"""Expiry dry-run and reappearance monitoring (to_change.md 5.1, 5.3, 9.12).

5.1 originally justified its one-week window with "the close rule is 5 consecutive
absences". 3.2 revised that to 3. The week stands, but the reason changed: at 3 absences
the probe is load-bearing, so the dry-run must exercise the whole state machine rather
than just the counter.

The point of the checklist is that "we ran it for a week" and "we verified it" are
different claims, and only the second justifies turning expiry on.
"""

from __future__ import annotations

from datetime import date

from job_finder.core.expiry_dryrun import DryRunChecklist, ExpiryDryRun
from job_finder.core.job_probe import JobProbeResult, ProbeVerdict
from job_finder.core.lifecycle import CompanyRunContext, JobLifecycleState, JobStatus
from job_finder.core.reappearance import ReappearanceEvent, ReappearanceMonitor

TODAY = date(2026, 9, 30)


def _context(**overrides: object) -> CompanyRunContext:
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
        verdict=verdict, reason_code=reason, status_code=200, final_url=None, detail=""
    )


def _observe(
    dry_run: ExpiryDryRun,
    state: JobLifecycleState,
    *,
    probe: JobProbeResult | None,
    context: CompanyRunContext | None = None,
    job_key: str = "job-1",
) -> JobLifecycleState:
    return dry_run.observe_absence(
        job_key=job_key,
        company_id="example",
        canonical_url="https://jobs.example.com/1",
        state=state,
        context=context or _context(),
        probe=probe,
        today=TODAY,
    )


def test_dry_run_reports_a_close_without_performing_it() -> None:
    """Report-only is the entire point (5.1)."""
    dry_run = ExpiryDryRun()
    state = JobLifecycleState(sighting_count=5, consecutive_absences=2)

    after = _observe(dry_run, state, probe=None)

    assert len(dry_run.would_close) == 1
    assert dry_run.would_close[0].reason_code == "absence_threshold"
    assert after.status is JobStatus.ACTIVE, "the dry run must not actually close anything"
    # The counter still advances, so a subsequent real run reaches the same conclusion.
    assert after.consecutive_absences == 3


def test_dry_run_uses_the_real_state_machine() -> None:
    """A parallel simplified implementation would verify the wrong thing.

    The guards must apply identically -- here, the two-sighting guard prevents a close
    the counter alone would have produced.
    """
    dry_run = ExpiryDryRun()
    state = JobLifecycleState(sighting_count=1, consecutive_absences=2)

    _observe(dry_run, state, probe=None)

    assert dry_run.would_close == [], "the sightings guard must apply in the dry run too"


def test_checklist_requires_the_probe_to_fire_on_every_first_absence() -> None:
    """Requirement 1 -- the gate on decision F (10.F)."""
    dry_run = ExpiryDryRun()

    _observe(dry_run, JobLifecycleState(sighting_count=5), probe=_probe(ProbeVerdict.LIVE))
    assert dry_run.checklist.probe_fires_on_first_absence is True

    # A first absence with no probe breaks the guarantee.
    _observe(dry_run, JobLifecycleState(sighting_count=5), probe=None, job_key="job-2")

    assert dry_run.checklist.first_absences_seen == 2
    assert dry_run.checklist.first_absences_probed == 1
    assert dry_run.checklist.probe_fires_on_first_absence is False
    assert "probe did not fire on 1 first absence(s)" in dry_run.checklist.unmet_requirements()


def test_an_unobserved_checklist_is_not_a_passing_checklist() -> None:
    """Vacuous truth is the failure mode.

    A dry-run week that happened to see no absences must not read as verified.
    """
    checklist = DryRunChecklist()

    assert checklist.probe_fires_on_first_absence is False
    assert checklist.satisfied is False
    assert "no first absences observed at all" in checklist.unmet_requirements()


def test_checklist_is_satisfied_only_after_all_four_are_observed() -> None:
    dry_run = ExpiryDryRun()

    # 1: probe fires on first absence, and 2: live-but-missing entered.
    _observe(
        dry_run,
        JobLifecycleState(sighting_count=5),
        probe=_probe(ProbeVerdict.LIVE_BUT_MISSING),
    )
    assert dry_run.checklist.live_but_missing_entered == 1
    assert dry_run.checklist.satisfied is False

    # 3: timeout / 429 / 503 advance nothing.
    _observe(
        dry_run,
        JobLifecycleState(sighting_count=5, consecutive_absences=1),
        probe=_probe(ProbeVerdict.NO_INFORMATION, "probe_timeout"),
        job_key="job-2",
    )
    assert dry_run.checklist.no_information_frozen == 1
    assert dry_run.checklist.satisfied is False

    # 4: an incomplete listing never feeds the counter (3.4).
    _observe(
        dry_run,
        JobLifecycleState(sighting_count=5, consecutive_absences=1),
        probe=_probe(ProbeVerdict.LIVE),
        context=_context(listing_complete=False),
        job_key="job-3",
    )

    assert dry_run.checklist.incomplete_listing_frozen == 1
    assert dry_run.checklist.satisfied is True
    assert dry_run.checklist.unmet_requirements() == ()


def test_page_cap_truncation_never_produces_a_would_close() -> None:
    """The 3.4 link: only an EXHAUSTED run may feed the absence counter."""
    dry_run = ExpiryDryRun()
    state = JobLifecycleState(sighting_count=5, consecutive_absences=2)

    after = _observe(
        dry_run, state, probe=_probe(ProbeVerdict.LIVE), context=_context(listing_complete=False)
    )

    assert dry_run.would_close == []
    assert after.consecutive_absences == 2


def test_dry_run_report_is_serializable_and_names_what_is_unmet() -> None:
    dry_run = ExpiryDryRun()
    _observe(dry_run, JobLifecycleState(sighting_count=5, consecutive_absences=2), probe=None)

    payload = dry_run.as_json()

    assert payload["would_close_count"] == 1
    assert payload["checklist_satisfied"] is False
    assert payload["unmet_requirements"], "an unsatisfied checklist must say why"
    assert payload["reason_counts"] == {"absence_threshold": 1}


# ---------------------------------------------------------------------------
# 5.3 reappearance monitoring
# ---------------------------------------------------------------------------


def _event(job_key: str, *, probed_gone: bool = False) -> ReappearanceEvent:
    return ReappearanceEvent(
        job_key=job_key,
        company_id="example",
        canonical_url=f"https://jobs.example.com/{job_key}",
        absences_before_return=1,
        was_probed_gone=probed_gone,
    )


def test_routine_reappearance_is_not_flagged() -> None:
    """5.3: reappearance is not inherently an error.

    Recruiter republish, board rotation and search-index lag all produce it. Alerting on
    each one means investigating normal churn daily, which means investigating nothing.
    """
    monitor = ReappearanceMonitor()
    for index in range(3):
        monitor.record(_event(f"job-{index}"))

    assert monitor.sources_needing_review() == ()


def test_a_burst_from_one_source_is_flagged() -> None:
    """'Dozens in a day from one company is a bug' -- the rate is the trigger."""
    monitor = ReappearanceMonitor(daily_threshold=10)
    for index in range(12):
        monitor.record(_event(f"job-{index}"))

    flagged = monitor.sources_needing_review()

    assert [item.company_id for item in flagged] == ["example"]
    assert flagged[0].reappearance_count == 12


def test_return_after_a_definitive_404_is_always_anomalous() -> None:
    """The one shape that is anomalous regardless of rate.

    Absent, the URL 404s, and it later returns: something concluded the job was
    definitively gone and was wrong.
    """
    monitor = ReappearanceMonitor(daily_threshold=100)
    monitor.record(_event("job-1", probed_gone=True))

    flagged = monitor.sources_needing_review()

    assert len(flagged) == 1
    assert flagged[0].probed_gone_count == 1
    assert flagged[0].exceeded_threshold is False, "flagged on shape, not on rate"


def test_monitor_report_is_serializable() -> None:
    monitor = ReappearanceMonitor()
    monitor.record(_event("job-1"))
    monitor.record(_event("job-2", probed_gone=True))

    payload = monitor.as_json()

    assert payload["total_reappearances"] == 2
    assert payload["sources_needing_review"] == ["example"]
