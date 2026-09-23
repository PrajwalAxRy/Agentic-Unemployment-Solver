"""End-to-end manual scan orchestration and machine-readable reporting."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from job_finder.adapters.base import AdapterRegistry, JobDetailAdapter
from job_finder.adapters.http_client import HttpRequestError
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.search_profile import SearchProfile
from job_finder.core.source_contracts import AdapterOutcome, CompanySource
from job_finder.filter_verification import (
    CandidateSection,
    FilterListingRecord,
    FilterVerificationReport,
    FinalFilterDecision,
    verify_filters,
)
from job_finder.filters.description_relevance import (
    DescriptionRelevanceDecision,
    DescriptionRelevanceResult,
    evaluate_substantive_ai_work,
)
from job_finder.filters.roles import RoleDecision
from job_finder.matching.evaluator import LLMProviderError, SeniorityEvaluator, UsageSnapshot
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
            filtered = verify_filters(
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
    progress: Callable[[str], None] | None = None,
) -> ScanReport:
    """Process one deterministic filter result through description, cache, and LLM stages."""
    sources = {entry.source.company_id: entry.source for entry in registry.entries}
    matches: list[MatchingJobRecord] = []
    uncertain_dates: list[MatchingJobRecord] = []
    reviews = _filter_reviews(filtered)
    counts = _ProcessingCounts(review=len(reviews))
    observed_at = _aware_from_iso(filtered.scan_at)
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
        counts.observed += 1
        counts.new += observation.is_new
        reportable = prior is None or prior.evaluation_status is not EvaluationStatus.COMPLETED
        if not _needs_processing(observation.record, observation.needs_evaluation, evaluator):
            counts.duplicate += 1
            counts.cache_hit += observation.record.evaluation_status is EvaluationStatus.COMPLETED
            continue

        detailed, fetched = _ensure_description(row.normalized_job, source, adapters, profile)
        counts.detail_fetch += fetched
        if detailed is None:
            counts.detail_failure += 1
            counts.review += 1
            if reportable:
                reviews.append(
                    _review(row, "description_unavailable", "full description is unavailable")
                )
            continue

        repository.prepare_evaluation(
            detailed,
            profile_version=profile.version,
            prompt_version=evaluator.prompt_version,
            model_policy=evaluator.model_policy,
        )
        relevance: DescriptionRelevanceResult | None = None
        if row.role.decision is RoleDecision.CONDITIONAL_DESCRIPTION:
            relevance = evaluate_substantive_ai_work(
                detailed.description,
                policy=profile.conditional_description,
            )
            if relevance.decision is not DescriptionRelevanceDecision.PASS:
                counts.conditional_reject += 1
                repository.fail_evaluation(
                    observation.record.job_key,
                    _relevance_failure(relevance, evaluator),
                )
                if relevance.decision is DescriptionRelevanceDecision.REVIEW and reportable:
                    counts.review += 1
                    reviews.append(
                        _review(
                            row,
                            relevance.reason_code,
                            relevance.reason,
                            evidence=relevance.evidence,
                        )
                    )
                continue
            counts.conditional_pass += 1

        try:
            result = service.evaluate(
                detailed,
                eligibility=CandidateEligibility.ELIGIBLE,
                profile_version=profile.version,
                target_description=profile.seniority.description,
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
) -> tuple[NormalizedJob | None, int]:
    if job.description is not None and job.description_hash is not None:
        return job, 0
    adapter = adapters.resolve(source)
    if not isinstance(adapter, JobDetailAdapter):
        return None, 0
    try:
        detailed = normalize_job(
            adapter.get_job_detail(source, job),
            location_policy=profile.location,
        )
    except (HttpRequestError, ValueError):
        return None, 1
    if detailed.description is None or detailed.description_hash is None:
        return None, 1
    return detailed, 1


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


def _relevance_failure(
    relevance: DescriptionRelevanceResult,
    evaluator: SeniorityEvaluator,
) -> dict[str, object]:
    return {
        "pipeline_disposition": (
            "role_rejected"
            if relevance.decision is DescriptionRelevanceDecision.REJECT
            else "manual_review"
        ),
        "reason_code": relevance.reason_code,
        "reason": relevance.reason,
        "evidence": relevance.evidence,
        "matched_topic": relevance.matched_topic,
        "matched_action": relevance.matched_action,
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
            exception_reason=entry.source.exception_reason,
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
