"""End-to-end manual scan orchestration and machine-readable reporting."""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from job_finder.adapters.base import AdapterRegistry, JobDetailAdapter
from job_finder.adapters.errors import DetailUnavailable, exception_category
from job_finder.adapters.http_client import HttpRequestError
from job_finder.collection import (
    CandidateSection,
    FilterListingRecord,
    FilterVerificationReport,
    FinalFilterDecision,
    collect_listings,
)
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.expiry_dryrun import ExpiryDryRun
from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.job_probe import JobProbeResult
from job_finder.core.lifecycle import (
    CompanyRunContext,
    JobLifecycleState,
    JobStatus,
    record_absence,
    record_sighting,
)
from job_finder.core.reappearance import ReappearanceEvent, ReappearanceMonitor
from job_finder.core.search_profile import SearchProfile
from job_finder.core.source_contracts import AdapterOutcome, CompanySource
from job_finder.filters.locations import LocationDecision
from job_finder.filters.roles import RoleDecision
from job_finder.matching.evaluator import LLMProviderError, SeniorityEvaluator, UsageSnapshot
from job_finder.matching.relevance_set import RelevanceVerdict
from job_finder.matching.seniority import SeniorityDecision
from job_finder.matching.service import (
    CachedEvaluationDisposition,
    CachedSeniorityEvaluationService,
    CandidateEligibility,
)
from job_finder.normalization.jobs import normalize_job
from job_finder.persistence.database import migrated_database
from job_finder.persistence.identity import job_identity
from job_finder.persistence.locking import ScanLock
from job_finder.persistence.repository import EvaluationStatus, JobRecord, JobStateRepository
from job_finder.persistence.runs import ScanRunRepository, ScanRunStatus

SCAN_REPORT_SCHEMA_VERSION = 1

_LOGGER = logging.getLogger(__name__)


class ScanOutcome(StrEnum):
    """Overall scan outcome used by reports and process exit codes."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"

    @property
    def exit_code(self) -> int:
        """Return the documented process exit status for this run outcome."""
        return {
            ScanOutcome.COMPLETE: 0,
            ScanOutcome.PARTIAL: 2,
            ScanOutcome.FAILED: 3,
        }[self]


@dataclass(frozen=True, slots=True)
class CompanyAccountingRecord:
    """One canonical company retained in complete-registry accounting."""

    company_id: str
    company_name: str
    enabled: bool
    status: str
    adapter_type: str
    exception_reason: str | None


@dataclass(frozen=True, slots=True)
class SourceFailureRecord:
    """One enabled company whose source did not complete successfully."""

    company_id: str
    company_name: str
    adapter_type: str
    outcome: str
    exception_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchingJobRecord:
    """A newly reportable job accepted by the seniority evaluator."""

    company_name: str
    title: str
    location: str
    publication_date: str | None
    raw_date_text: str | None
    date_basis: str
    first_seen_at: str
    seniority_decision: str
    seniority_evidence: str
    seniority_reason: str
    canonical_url: str


@dataclass(frozen=True, slots=True)
class ReviewCandidateRecord:
    """A new candidate kept visible because a deterministic or LLM step needs review."""

    company_name: str
    title: str
    location: str
    category: str
    reason: str
    candidate_section: str
    canonical_url: str
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class ScanMetrics:
    """Reconciled aggregate counts for one end-to-end scan."""

    canonical_company_count: int
    enabled_company_count: int
    disabled_company_count: int
    attempted_company_count: int
    successful_company_count: int
    valid_empty_company_count: int
    failed_company_count: int
    listing_count: int
    recency_candidate_count: int
    role_candidate_count: int
    retained_candidate_count: int
    location_review_count: int
    observed_identity_count: int
    new_identity_count: int
    duplicate_suppressed_count: int
    description_fetch_count: int
    description_failure_count: int
    conditional_pass_count: int
    conditional_rejection_count: int
    relevance_peripheral_count: int
    llm_location_rejection_count: int
    llm_evaluated_count: int
    llm_cache_hit_count: int
    seniority_match_count: int
    seniority_rejection_count: int
    seniority_review_count: int


@dataclass(frozen=True, slots=True)
class ScanReport:
    """Complete sanitized output for one manually triggered scan."""

    schema_version: int
    run_id: str
    started_at: str
    completed_at: str
    duration_seconds: float
    outcome: ScanOutcome
    registry_version: str
    profile_id: str
    profile_version: str
    profile_hash: str
    prompt_version: str
    model_policy: str
    source_outcomes: Mapping[str, int]
    company_status_counts: Mapping[str, int]
    metrics: ScanMetrics
    usage: UsageSnapshot
    matching_jobs: tuple[MatchingJobRecord, ...]
    date_uncertain_jobs: tuple[MatchingJobRecord, ...]
    review_candidates: tuple[ReviewCandidateRecord, ...]
    source_failures: tuple[SourceFailureRecord, ...]
    company_accounting: tuple[CompanyAccountingRecord, ...]
    lifecycle: Mapping[str, object] | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome.value,
            "registry_version": self.registry_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "prompt_version": self.prompt_version,
            "model_policy": self.model_policy,
            "source_outcomes": dict(self.source_outcomes),
            "company_status_counts": dict(self.company_status_counts),
            "metrics": asdict(self.metrics),
            "usage": asdict(self.usage),
            "matching_jobs": [asdict(item) for item in self.matching_jobs],
            "date_uncertain_jobs": [asdict(item) for item in self.date_uncertain_jobs],
            "review_candidates": [asdict(item) for item in self.review_candidates],
            "source_failures": [asdict(item) for item in self.source_failures],
            "company_accounting": [asdict(item) for item in self.company_accounting],
            "lifecycle": dict(self.lifecycle) if self.lifecycle else None,
        }


@dataclass(slots=True)
class _ProcessingCounts:
    observed: int = 0
    new: int = 0
    duplicate: int = 0
    detail_fetch: int = 0
    detail_failure: int = 0
    conditional_pass: int = 0
    conditional_reject: int = 0
    relevance_peripheral: int = 0
    location_rejected: int = 0
    evaluated: int = 0
    cache_hit: int = 0
    match: int = 0
    reject: int = 0
    review: int = 0


def run_manual_scan(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    evaluator: SeniorityEvaluator,
    *,
    database_path: Path,
    lock_path: Path,
    source_retry_count: int = 2,
    expiry_dry_run: bool = True,
    job_probe: Callable[[str, bool], JobProbeResult | None] | None = None,
    started_at: datetime | None = None,
    run_id: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScanReport:
    """Run every pipeline layer under one lock and persist sanitized run metrics."""
    start = started_at or datetime.now().astimezone()
    if start.tzinfo is None:
        raise ValueError("started_at must be timezone-aware")
    identifier = run_id or _new_run_id(start)
    with ScanLock(lock_path), migrated_database(database_path) as connection:
        jobs = JobStateRepository(connection)
        runs = ScanRunRepository(connection)
        runs.start(
            identifier,
            started_at=start,
            registry_version=registry.registry_version,
            profile_version=profile.version,
            prompt_version=evaluator.prompt_version,
            model_policy=evaluator.model_policy,
        )
        try:
            if progress is not None:
                progress(
                    "phase=source_collection status=started "
                    f"companies={sum(entry.source.enabled for entry in registry.entries)}"
                )
            filtered = collect_listings(
                registry,
                adapters,
                profile,
                source_retry_count=source_retry_count,
                first_seen_lookup=lambda job: _first_seen(jobs, job),
                progress=progress,
            )
            retained_count = sum(
                row.final_decision is FinalFilterDecision.RETAINED for row in filtered.listings
            )
            if progress is not None:
                progress(
                    "phase=deterministic_filter status=complete "
                    f"listings={filtered.listing_count} retained={retained_count}"
                )
            report = process_filter_report(
                filtered,
                registry,
                adapters,
                profile,
                evaluator,
                jobs,
                run_id=identifier,
                started_at=start,
                completed_at=None,
                expiry_dry_run=expiry_dry_run,
                job_probe=job_probe,
                progress=progress,
            )
            completed = _aware_from_iso(report.completed_at)
            runs.finish(
                identifier,
                completed_at=completed,
                status=_run_status(report.outcome),
                metrics=asdict(report.metrics),
            )
            if progress is not None:
                progress(
                    "phase=candidate_evaluation status=complete "
                    f"observed={report.metrics.observed_identity_count} "
                    f"evaluated={report.metrics.llm_evaluated_count}"
                )
            return report
        except BaseException as error:
            completed = datetime.now().astimezone()
            runs.finish(
                identifier,
                completed_at=completed,
                status=ScanRunStatus.FAILED,
                metrics={"error_type": type(error).__name__},
            )
            raise


def process_filter_report(
    filtered: FilterVerificationReport,
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    evaluator: SeniorityEvaluator,
    repository: JobStateRepository,
    *,
    run_id: str,
    started_at: datetime,
    completed_at: datetime | None,
    expiry_dry_run: bool = True,
    job_probe: Callable[[str, bool], JobProbeResult | None] | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScanReport:
    """Process one deterministic filter result through description, cache, and LLM stages."""
    sources = {entry.source.company_id: entry.source for entry in registry.entries}
    matches: list[MatchingJobRecord] = []
    uncertain_dates: list[MatchingJobRecord] = []
    reviews = _filter_reviews(filtered)
    counts = _ProcessingCounts(review=len(reviews))
    observed_at = _aware_from_iso(filtered.scan_at)
    # Every job key seen in this run's listings. Whatever is active in the store but
    # missing from here is a candidate absence (3.2).
    seen_job_keys: set[str] = set()
    service = CachedSeniorityEvaluationService(repository=repository, evaluator=evaluator)
    retained_total = sum(
        row.final_decision is FinalFilterDecision.RETAINED for row in filtered.listings
    )
    retained_index = 0
    if progress is not None:
        progress(f"phase=candidate_evaluation status=started retained={retained_total}")

    for row in filtered.listings:
        if row.final_decision is not FinalFilterDecision.RETAINED:
            continue
        retained_index += 1
        if progress is not None and (
            retained_index == 1 or retained_index % 10 == 0 or retained_index == retained_total
        ):
            progress(
                f"phase=candidate_evaluation progress={retained_index}/{retained_total} "
                f"company={row.company_id}"
            )
        source = sources[row.company_id]
        prior = repository.get(job_identity(row.normalized_job).job_key)
        observation = repository.observe_listing(
            row.normalized_job,
            observed_at=observed_at,
            profile_version=profile.version,
        )
        seen_job_keys.add(observation.record.job_key)
        counts.observed += 1
        counts.new += observation.is_new
        reportable = prior is None or prior.evaluation_status is not EvaluationStatus.COMPLETED
        if not _needs_processing(observation.record, observation.needs_evaluation, evaluator):
            counts.duplicate += 1
            counts.cache_hit += observation.record.evaluation_status is EvaluationStatus.COMPLETED
            continue

        detailed, fetched, failure_category = _ensure_description(
            row.normalized_job, source, adapters, profile
        )
        counts.detail_fetch += fetched
        if detailed is None:
            counts.detail_failure += 1
            counts.review += 1
            if reportable:
                reviews.append(
                    _review(
                        row,
                        "description_unavailable",
                        f"full description is unavailable ({failure_category})",
                        evidence=failure_category,
                    )
                )
            continue

        repository.prepare_evaluation(
            detailed,
            profile_version=profile.version,
            prompt_version=evaluator.prompt_version,
            model_policy=evaluator.model_policy,
        )
        # The regex relevance gate that used to run here has been removed (to_change.md
        # 2.3). It fired ten times in the entire 2026-09-29 scan -- it was never the real
        # AI filter, title substring matching was. Keeping it while 2.2a widens the title
        # stage would have been actively harmful: every row now reaches this point, so a
        # gate tuned as a rare special case would become the universal filter and reject
        # almost everything on a keyword miss.
        #
        # Relevance is now one of the three judgments in the merged LLM call (2.5), which
        # sees the description and can tell a team name from the actual work.
        if row.role.decision is RoleDecision.CONDITIONAL_DESCRIPTION:
            counts.conditional_pass += 1

        # 2.4/2.5: ask the model about location only when the deterministic filter could
        # not resolve it, which in practice means an unqualified remote posting.
        unresolved_location = (
            row.location_original
            if row.location is not None and row.location.decision is LocationDecision.REVIEW
            else None
        )
        try:
            result = service.evaluate(
                detailed,
                eligibility=CandidateEligibility.ELIGIBLE,
                profile_version=profile.version,
                target_description=profile.seniority.description,
                location_original=unresolved_location,
            )
        except LLMProviderError as error:
            counts.review += 1
            if reportable:
                reviews.append(_review(row, "llm_provider_failure", str(error)))
            continue

        if result.disposition is CachedEvaluationDisposition.CACHED:
            counts.cache_hit += 1
        elif result.disposition is CachedEvaluationDisposition.EVALUATED:
            counts.evaluated += 1
        elif result.disposition is CachedEvaluationDisposition.MANUAL_REVIEW:
            counts.review += 1
            if reportable:
                reason = (
                    "; ".join(result.evaluation.errors) if result.evaluation else "invalid output"
                )
                reviews.append(_review(row, "invalid_seniority_output", reason))
            continue
        if result.decision is None:
            raise AssertionError("completed or cached evaluation requires a seniority decision")

        # 2.3 / 2.6: the relevance gate. This is the only thing standing behind the
        # widened title filter -- 2.2a took the title pass rate from 11% to ~70%, so
        # without this every engineering title in India reaches the report.
        #
        # Only a confident "unrelated" drops a row. "peripheral" is displayed, tiered
        # lower: forcing it into a binary would hide the uncertainty rather than remove
        # it, and lose the signal showing which rows deserve a click.
        judgment = getattr(evaluator, "last_judgment", None)
        if judgment is not None and judgment.relevance is RelevanceVerdict.UNRELATED:
            counts.conditional_reject += 1
            repository.fail_evaluation(
                observation.record.job_key,
                {
                    "pipeline_disposition": "role_rejected",
                    "reason_code": "not_ai_ml_work",
                    "reason": judgment.relevance_reason,
                    "evidence": judgment.relevance_evidence,
                    "prompt_version": evaluator.prompt_version,
                    "model_policy": evaluator.model_policy,
                },
            )
            _LOGGER.debug(
                "relevance_rejected company=%s title=%s reason=%s",
                row.company_id,
                row.title_original,
                judgment.relevance_reason,
            )
            continue
        if judgment is not None:
            counts.relevance_peripheral += judgment.relevance is RelevanceVerdict.PERIPHERAL
            # 3.6: verdict_at is set once, the first time a job reaches a qualifying
            # verdict. The feed sorts on it rather than on first sighting, which is what
            # lets rows recovered from the normalization bug surface as new despite
            # carrying old first_seen_at values.
            repository.record_verdict(
                observation.record.job_key,
                verdict=judgment.relevance.value,
                verdict_at=observed_at,
                required_experience=judgment.required_experience,
            )
            # 2.4: an unqualified-remote row the model judged ineligible for India.
            if judgment.location_eligible is False:
                counts.location_rejected += 1
                continue

        _record_decision(
            row,
            result.decision,
            result.record or observation.record,
            reportable=reportable,
            matches=matches,
            uncertain_dates=uncertain_dates,
            reviews=reviews,
            counts=counts,
        )

    lifecycle_report = _run_lifecycle(
        filtered,
        repository=repository,
        seen_job_keys=seen_job_keys,
        today=observed_at.date(),
        probe=job_probe,
        dry_run=expiry_dry_run,
        progress=progress,
    )

    finish = completed_at or datetime.now().astimezone()
    outcome = _scan_outcome(filtered)
    accounting = _company_accounting(registry)
    source_failures = _source_failures(filtered)
    metrics = _metrics(filtered, accounting, source_failures, counts)
    return ScanReport(
        schema_version=SCAN_REPORT_SCHEMA_VERSION,
        run_id=run_id,
        started_at=started_at.isoformat(),
        completed_at=finish.isoformat(),
        duration_seconds=max(0.0, round((finish - started_at).total_seconds(), 3)),
        outcome=outcome,
        registry_version=registry.registry_version,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        profile_hash=profile.content_hash,
        prompt_version=evaluator.prompt_version,
        model_policy=evaluator.model_policy,
        source_outcomes=dict(filtered.outcome_counts),
        company_status_counts=dict(sorted(Counter(item.status for item in accounting).items())),
        metrics=metrics,
        usage=evaluator.usage,
        matching_jobs=tuple(matches),
        date_uncertain_jobs=tuple(uncertain_dates),
        review_candidates=tuple(reviews),
        source_failures=source_failures,
        company_accounting=accounting,
        lifecycle=asdict(lifecycle_report),
    )


def write_scan_report(report: ScanReport, path: Path) -> None:
    """Write the complete sanitized machine-readable scan report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _needs_processing(
    record: JobRecord,
    pending: bool,
    evaluator: SeniorityEvaluator,
) -> bool:
    if pending:
        return True
    if record.evaluation_status is EvaluationStatus.COMPLETED:
        return (
            record.prompt_version != evaluator.prompt_version
            or record.model_policy != evaluator.model_policy
        )
    result = record.seniority_result or {}
    if result.get("reason_code") in {"description_unavailable", "llm_provider_failure"}:
        return True
    return result.get("pipeline_disposition") == "manual_review" and (
        result.get("prompt_version") != evaluator.prompt_version
        or result.get("model_policy") != evaluator.model_policy
    )


def _ensure_description(
    job: NormalizedJob,
    source: CompanySource,
    adapters: AdapterRegistry,
    profile: SearchProfile,
) -> tuple[NormalizedJob | None, int, str | None]:
    """Fetch a full description, returning ``(job, fetch_count, failure_category)``.

    The third element is the reason the fetch failed, or ``None`` on success. It exists
    because this function previously reported every failure as an unexplained
    ``description_unavailable``: a 403, a redirect and "the adapter's title guard broke"
    were indistinguishable. That is how the title-normalization bug hid behind what looked
    like a network problem across 97 rows (``to_change.md`` 1.1).
    """
    if job.description is not None and job.description_hash is not None:
        return job, 0, None
    adapter = adapters.resolve(source)
    if not isinstance(adapter, JobDetailAdapter):
        return None, 0, "detail_not_supported"
    try:
        detailed = normalize_job(
            adapter.get_job_detail(source, job),
            location_policy=profile.location,
        )
    except HttpRequestError as error:
        _LOGGER.warning(
            "detail_fetch_failed company=%s url=%s category=%s status=%s reason=%s",
            source.company_id,
            job.canonical_url,
            error.category.value,
            getattr(error, "status_code", None),
            error,
        )
        return None, 1, f"http_{error.category.value}"
    except DetailUnavailable as error:
        # Identity mismatches mean an adapter assumption broke, not that the site is down.
        # Logged at ERROR with a traceback so a burst of them is visible rather than
        # aggregating silently into the review queue.
        _LOGGER.exception(
            "detail_fetch_failed company=%s url=%s category=%s reason=%s",
            source.company_id,
            job.canonical_url,
            exception_category(error),
            error,
        )
        return None, 1, exception_category(error)
    except ValueError as error:
        # Adapters not yet migrated to the taxonomy still raise bare ValueError.
        _LOGGER.exception(
            "detail_fetch_failed company=%s url=%s category=untyped_value_error reason=%s",
            source.company_id,
            job.canonical_url,
            error,
        )
        return None, 1, "untyped_value_error"
    if detailed.description is None or detailed.description_hash is None:
        _LOGGER.warning(
            "detail_fetch_empty company=%s url=%s",
            source.company_id,
            job.canonical_url,
        )
        return None, 1, "empty_description"
    return detailed, 1, None


@dataclass(frozen=True, slots=True)
class LifecycleReport:
    """What the lifecycle pass did, and what expiry would have done."""

    dry_run: bool
    sightings: int
    absences: int
    probes_fired: int
    closed: int
    would_close: int
    checklist: Mapping[str, object]
    checklist_satisfied: bool
    unmet_requirements: tuple[str, ...]
    reappearance: Mapping[str, object]


def _run_lifecycle(
    filtered: FilterVerificationReport,
    *,
    repository: JobStateRepository,
    seen_job_keys: set[str],
    today: date,
    probe: Callable[[str, bool], JobProbeResult | None] | None,
    dry_run: bool,
    progress: Callable[[str], None] | None,
) -> LifecycleReport:
    """Record sightings and absences, probing on first absence (3.2, 3.3, 5.1, 5.3).

    Runs in dry-run mode by default. 5.1 requires about a week of report-only observation
    before expiry closes anything, and the week is justified by the probe being
    load-bearing at a 3-absence threshold rather than by the threshold itself (9.12).
    """
    dry = ExpiryDryRun()
    monitor = ReappearanceMonitor()
    sightings = absences = probes_fired = closed = 0

    for company in filtered.companies:
        # Guard 1 and the 3.4 link: absence means nothing unless the run that failed to
        # see the job was itself trustworthy.
        context = CompanyRunContext(
            scan_succeeded=company.outcome
            in {AdapterOutcome.SUCCESS.value, AdapterOutcome.EMPTY.value},
            listing_complete=company.complete,
            current_listing_count=company.listing_count,
            previous_listing_count=None,
        )
        for record in repository.active_jobs_for_company(company.company_id):
            state = JobLifecycleState(
                status=JobStatus(record.status),
                consecutive_absences=record.consecutive_absences,
                sighting_count=record.sighting_count,
                live_but_missing_days=record.live_but_missing_days,
                probe_state=record.probe_state,
                closed_at=record.closed_at,
                last_seen=record.last_seen_at.date(),
            )

            if record.job_key in seen_job_keys:
                if state.consecutive_absences > 0 or state.live_but_missing_days > 0:
                    # Returned after being absent. Routine by default (5.3); only the
                    # per-source rate and the after-404 shape are anomalous.
                    monitor.record(
                        ReappearanceEvent(
                            job_key=record.job_key,
                            company_id=record.company_id,
                            canonical_url=record.canonical_url,
                            absences_before_return=state.consecutive_absences,
                            was_probed_gone=state.probe_state
                            in {"http_gone", "closed_page_text", "redirected_to_search"},
                        )
                    )
                updated = record_sighting(state, today=today)
                sightings += 1
            else:
                absences += 1
                probe_result: JobProbeResult | None = None
                # 3.2: the probe must fire on FIRST absence. At a 3-absence threshold it
                # is the only thing between a silently truncated listing and a closed
                # live job.
                if probe is not None and context.trustworthy_for_expiry:
                    probe_result = probe(record.canonical_url, False)
                    probes_fired += probe_result is not None
                if dry_run:
                    updated = dry.observe_absence(
                        job_key=record.job_key,
                        company_id=record.company_id,
                        canonical_url=record.canonical_url,
                        state=state,
                        context=context,
                        probe=probe_result,
                        today=today,
                    )
                else:
                    updated = record_absence(
                        state, context=context, probe=probe_result, today=today
                    )
                    closed += updated.status is JobStatus.CLOSED

            repository.record_lifecycle(record.job_key, updated)

    if progress is not None:
        progress(
            f"phase=lifecycle mode={'dry_run' if dry_run else 'enforcing'} "
            f"sightings={sightings} absences={absences} probes={probes_fired} "
            f"{'would_close' if dry_run else 'closed'}="
            f"{len(dry.would_close) if dry_run else closed}"
        )

    payload = dry.as_json()
    return LifecycleReport(
        dry_run=dry_run,
        sightings=sightings,
        absences=absences,
        probes_fired=probes_fired,
        closed=closed,
        would_close=len(dry.would_close),
        checklist=payload["checklist"],  # type: ignore[arg-type]
        checklist_satisfied=bool(payload["checklist_satisfied"]),
        unmet_requirements=tuple(payload["unmet_requirements"]),  # type: ignore[arg-type]
        reappearance=monitor.as_json(),
    )


def _record_decision(
    row: FilterListingRecord,
    decision: SeniorityDecision,
    record: JobRecord,
    *,
    reportable: bool,
    matches: list[MatchingJobRecord],
    uncertain_dates: list[MatchingJobRecord],
    reviews: list[ReviewCandidateRecord],
    counts: _ProcessingCounts,
) -> None:
    if decision.seniority_match is True:
        counts.match += 1
        if reportable:
            item = _matching_job(row, decision, record)
            if row.candidate_section is CandidateSection.STRICT:
                matches.append(item)
            else:
                uncertain_dates.append(item)
    elif decision.seniority_match is False:
        counts.reject += 1
    else:
        counts.review += 1
        if reportable:
            reviews.append(
                _review(
                    row,
                    "seniority_uncertain",
                    decision.reason,
                    evidence=decision.evidence,
                )
            )


def _matching_job(
    row: FilterListingRecord,
    decision: SeniorityDecision,
    record: JobRecord,
) -> MatchingJobRecord:
    job = row.normalized_job
    return MatchingJobRecord(
        company_name=row.company_name,
        title=job.title_original,
        location=job.location_original,
        publication_date=_date_text(job.published_at),
        raw_date_text=job.published_at_raw,
        date_basis=job.date_basis.value,
        first_seen_at=record.first_seen_at.isoformat(timespec="seconds"),
        seniority_decision="match",
        seniority_evidence=decision.evidence,
        seniority_reason=decision.reason,
        canonical_url=job.canonical_url,
    )


def _filter_reviews(report: FilterVerificationReport) -> list[ReviewCandidateRecord]:
    return [
        _review(
            row,
            row.location.reason_code if row.location is not None else "filter_review",
            row.location.reason if row.location is not None else "deterministic filter review",
        )
        for row in report.listings
        if row.final_decision is FinalFilterDecision.REVIEW
    ]


def _review(
    row: FilterListingRecord,
    category: str,
    reason: str,
    *,
    evidence: str | None = None,
) -> ReviewCandidateRecord:
    return ReviewCandidateRecord(
        company_name=row.company_name,
        title=row.title_original,
        location=row.location_original,
        category=category,
        reason=reason,
        candidate_section=row.candidate_section.value,
        canonical_url=row.canonical_url,
        evidence=evidence,
    )


def _failure_result(reason_code: str, evaluator: SeniorityEvaluator) -> dict[str, object]:
    return {
        "pipeline_disposition": "manual_review",
        "reason_code": reason_code,
        "prompt_version": evaluator.prompt_version,
        "model_policy": evaluator.model_policy,
    }


def _company_accounting(
    registry: CompanySourceRegistry,
) -> tuple[CompanyAccountingRecord, ...]:
    return tuple(
        CompanyAccountingRecord(
            company_id=entry.source.company_id,
            company_name=entry.source.company_name,
            enabled=entry.source.enabled,
            status=entry.source.status.value,
            adapter_type=entry.source.adapter_type.value,
            exception_reason=(
                entry.source.exception_reason
                or (entry.source.notes if not entry.source.enabled else None)
            ),
        )
        for entry in sorted(registry.entries, key=lambda item: item.source_rank)
    )


def _source_failures(report: FilterVerificationReport) -> tuple[SourceFailureRecord, ...]:
    return tuple(
        SourceFailureRecord(
            company_id=company.company_id,
            company_name=company.company_name,
            adapter_type=company.adapter_type,
            outcome=company.outcome,
            exception_categories=company.exception_categories,
        )
        for company in report.companies
        if company.outcome not in {AdapterOutcome.SUCCESS.value, AdapterOutcome.EMPTY.value}
    )


def _metrics(
    filtered: FilterVerificationReport,
    accounting: tuple[CompanyAccountingRecord, ...],
    source_failures: tuple[SourceFailureRecord, ...],
    counts: _ProcessingCounts,
) -> ScanMetrics:
    successful = filtered.outcome_counts.get(AdapterOutcome.SUCCESS.value, 0)
    empty = filtered.outcome_counts.get(AdapterOutcome.EMPTY.value, 0)
    role_candidates = sum(
        value for key, value in filtered.role_counts.items() if key != RoleDecision.REJECT.value
    )
    return ScanMetrics(
        canonical_company_count=len(accounting),
        enabled_company_count=filtered.enabled_company_count,
        disabled_company_count=sum(not item.enabled for item in accounting),
        attempted_company_count=len(filtered.companies),
        successful_company_count=successful,
        valid_empty_company_count=empty,
        failed_company_count=len(source_failures),
        listing_count=filtered.listing_count,
        recency_candidate_count=filtered.strict_recent_count + filtered.uncertain_candidate_count,
        role_candidate_count=role_candidates,
        retained_candidate_count=filtered.final_counts.get(FinalFilterDecision.RETAINED.value, 0),
        location_review_count=filtered.final_counts.get(FinalFilterDecision.REVIEW.value, 0),
        observed_identity_count=counts.observed,
        new_identity_count=counts.new,
        duplicate_suppressed_count=counts.duplicate,
        description_fetch_count=counts.detail_fetch,
        description_failure_count=counts.detail_failure,
        conditional_pass_count=counts.conditional_pass,
        conditional_rejection_count=counts.conditional_reject,
        relevance_peripheral_count=counts.relevance_peripheral,
        llm_location_rejection_count=counts.location_rejected,
        llm_evaluated_count=counts.evaluated,
        llm_cache_hit_count=counts.cache_hit,
        seniority_match_count=counts.match,
        seniority_rejection_count=counts.reject,
        seniority_review_count=counts.review,
    )


def _scan_outcome(report: FilterVerificationReport) -> ScanOutcome:
    if report.healthy:
        return ScanOutcome.COMPLETE
    healthy_count = sum(
        report.outcome_counts.get(outcome.value, 0)
        for outcome in (AdapterOutcome.SUCCESS, AdapterOutcome.EMPTY)
    )
    return ScanOutcome.PARTIAL if healthy_count else ScanOutcome.FAILED


def _run_status(outcome: ScanOutcome) -> ScanRunStatus:
    return {
        ScanOutcome.COMPLETE: ScanRunStatus.COMPLETED,
        ScanOutcome.PARTIAL: ScanRunStatus.PARTIAL,
        ScanOutcome.FAILED: ScanRunStatus.FAILED,
    }[outcome]


def _first_seen(repository: JobStateRepository, job: NormalizedJob) -> datetime | None:
    record = repository.get(job_identity(job).job_key)
    return record.first_seen_at if record is not None else None


def _aware_from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("filter scan_at must be timezone-aware")
    return parsed


def _date_text(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _new_run_id(started_at: datetime) -> str:
    stamp = started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"scan-{stamp}-{uuid4().hex[:8]}"
