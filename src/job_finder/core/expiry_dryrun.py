"""Expiry dry-run: report what *would* close, without closing anything.

``to_change.md`` 5.1 requires report-only mode for about a week before expiry closes
anything for real. The doc originally justified the week by the 5-absence rule; 3.2
revised that to 3, and 9.12 corrected the reasoning. The week stands, but for a stronger
reason: **at 3 absences the probe is load-bearing**, so the dry-run has to exercise the
full state machine rather than just the counter. A 3-day run would only just reach a
single close, with no margin to observe the live-but-missing branch at all.

5.1 lists four things the dry-run must explicitly verify, and :class:`DryRunChecklist`
tracks each one so "we ran it for a week" cannot be mistaken for "we verified it":

1. the probe genuinely fires on first absence
2. the live-but-missing branch is entered and runs on its own clock
3. timeout / 429 / 503 advance nothing
4. ``page_cap_reached`` never feeds the absence counter (3.4)

Item 1 is the gate on decision F. If the probe does not demonstrably fire on first
absence during the dry-run week, revert the threshold to 5 until it does.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date

from job_finder.core.job_probe import JobProbeResult, ProbeVerdict
from job_finder.core.lifecycle import (
    CompanyRunContext,
    JobLifecycleState,
    JobStatus,
    record_absence,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WouldCloseRecord:
    """One job that expiry would have closed, had it been enabled."""

    job_key: str
    company_id: str
    canonical_url: str
    reason_code: str
    consecutive_absences: int
    live_but_missing_days: int
    sighting_count: int
    probe_state: str | None


@dataclass(slots=True)
class DryRunChecklist:
    """Observation counters for the four 5.1 verification requirements.

    These are counters rather than booleans on purpose. "The probe fired at least once"
    is much weaker evidence than "the probe fired on every one of 47 first absences", and
    only the second is worth turning expiry on for.
    """

    first_absences_seen: int = 0
    first_absences_probed: int = 0
    live_but_missing_entered: int = 0
    no_information_frozen: int = 0
    incomplete_listing_frozen: int = 0

    @property
    def probe_fires_on_first_absence(self) -> bool:
        """Requirement 1 -- the gate on decision F.

        Requires at least one observation. Vacuous truth is the failure mode: a dry-run
        week that happened to see no absences must not read as a passing check.
        """
        return (
            self.first_absences_seen > 0 and self.first_absences_probed == self.first_absences_seen
        )

    @property
    def satisfied(self) -> bool:
        """Whether all four requirements have been positively observed."""
        return (
            self.probe_fires_on_first_absence
            and self.live_but_missing_entered > 0
            and self.no_information_frozen > 0
            and self.incomplete_listing_frozen > 0
        )

    def unmet_requirements(self) -> tuple[str, ...]:
        """Name what has not been observed yet, for the operator."""
        unmet: list[str] = []
        if self.first_absences_seen == 0:
            unmet.append("no first absences observed at all")
        elif not self.probe_fires_on_first_absence:
            missed = self.first_absences_seen - self.first_absences_probed
            unmet.append(f"probe did not fire on {missed} first absence(s)")
        if self.live_but_missing_entered == 0:
            unmet.append("live-but-missing branch never entered")
        if self.no_information_frozen == 0:
            unmet.append("no timeout/429/503 probe observed")
        if self.incomplete_listing_frozen == 0:
            unmet.append("no incomplete listing observed")
        return tuple(unmet)


@dataclass(slots=True)
class ExpiryDryRun:
    """Accumulates what expiry would have done across a dry-run window."""

    checklist: DryRunChecklist = field(default_factory=DryRunChecklist)
    would_close: list[WouldCloseRecord] = field(default_factory=list)
    reason_counts: Counter[str] = field(default_factory=Counter)

    def observe_absence(
        self,
        *,
        job_key: str,
        company_id: str,
        canonical_url: str,
        state: JobLifecycleState,
        context: CompanyRunContext,
        probe: JobProbeResult | None,
        today: date,
    ) -> JobLifecycleState:
        """Run the real state machine, record the outcome, and suppress the close.

        The returned state is the genuine next state **except** that a close is downgraded
        back to active. Running the real logic is the point: a dry-run that used a
        parallel simplified implementation would verify the wrong thing.
        """
        if state.consecutive_absences == 0 and state.live_but_missing_days == 0:
            self.checklist.first_absences_seen += 1
            if probe is not None:
                self.checklist.first_absences_probed += 1
            else:
                _LOGGER.warning(
                    "dryrun_probe_missing job=%s url=%s (3.2 requires a probe on first absence)",
                    job_key,
                    canonical_url,
                )

        if not context.listing_complete or not context.scan_succeeded:
            self.checklist.incomplete_listing_frozen += 1
        if probe is not None and probe.verdict is ProbeVerdict.NO_INFORMATION:
            self.checklist.no_information_frozen += 1

        updated = record_absence(state, context=context, probe=probe, today=today)

        if updated.live_but_missing_days > state.live_but_missing_days:
            self.checklist.live_but_missing_entered += 1

        if updated.status is JobStatus.CLOSED:
            reason = probe.reason_code if probe is not None else "absence_threshold"
            self.reason_counts[reason] += 1
            self.would_close.append(
                WouldCloseRecord(
                    job_key=job_key,
                    company_id=company_id,
                    canonical_url=canonical_url,
                    reason_code=reason,
                    consecutive_absences=updated.consecutive_absences,
                    live_but_missing_days=updated.live_but_missing_days,
                    sighting_count=updated.sighting_count,
                    probe_state=updated.probe_state,
                )
            )
            _LOGGER.info(
                "dryrun_would_close job=%s company=%s reason=%s absences=%d",
                job_key,
                company_id,
                reason,
                updated.consecutive_absences,
            )
            # Suppress: report only.
            return JobLifecycleState(
                status=JobStatus.ACTIVE,
                consecutive_absences=updated.consecutive_absences,
                sighting_count=updated.sighting_count,
                live_but_missing_days=updated.live_but_missing_days,
                probe_state=updated.probe_state,
                closed_at=None,
                last_seen=updated.last_seen,
            )
        return updated

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "checklist": asdict(self.checklist),
            "checklist_satisfied": self.checklist.satisfied,
            "unmet_requirements": list(self.checklist.unmet_requirements()),
            "would_close_count": len(self.would_close),
            "reason_counts": dict(self.reason_counts),
            "would_close": [asdict(record) for record in self.would_close],
        }
