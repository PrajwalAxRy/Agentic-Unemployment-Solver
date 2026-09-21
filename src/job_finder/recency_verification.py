"""Registry-wide normalization and rolling-recency measurement."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry, JobSourceAdapter
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.recency import (
    CompanyDateCoverage,
    CompanyDateCoverageClass,
    CompanyDateCoverageInput,
    DecisionCounts,
    EvidenceCounts,
    ListingDateObservation,
    SourceAssessment,
    assess_listing_recency,
    build_date_coverage_report,
)
from job_finder.core.search_profile import SearchProfile
from job_finder.core.source_contracts import (
    AdapterOutcome,
    AdapterResult,
    CompanySource,
    IdentityStrategy,
)
from job_finder.normalization.jobs import normalize_job


@dataclass(frozen=True, slots=True)
class CompanyRecencyRecord:
    """Per-company outcome and per-listing evidence for the ignored H5 runtime report."""

    company_id: str
    company_name: str
    source_rank: int
    priority: str
    adapter_type: str
    outcome: str
    complete: bool
    attempt_count: int
    page_count: int
    listing_count: int
    valid_identity_count: int
    valid_url_count: int
    coverage_class: CompanyDateCoverageClass
    listing_counts: EvidenceCounts
    decision_counts: DecisionCounts
    first_seen_available_count: int
    exception_categories: tuple[str, ...]
    observations: tuple[ListingDateObservation, ...]


@dataclass(frozen=True, slots=True)
class AdapterRecencySummary:
    """Required adapter-level normalization and date-coverage metrics."""

    adapter_type: str
    company_count: int
    outcome_counts: Mapping[str, int]
    company_class_counts: Mapping[CompanyDateCoverageClass, int]
    listing_count: int
    valid_identity_count: int
    valid_url_count: int
    listing_counts: EvidenceCounts
    decision_counts: DecisionCounts
    first_seen_available_count: int


@dataclass(frozen=True, slots=True)
class RecencyVerificationReport:
    """Complete full-registry report used to make the mandatory H5 decision."""

    schema_version: int
    generated_at: str
    scan_at: str
    boundary: str
    window_days: int
    source_retry_count: int
    registry_version: str
    profile_id: str
    profile_version: str
    profile_hash: str
    enabled_company_count: int
    outcome_counts: Mapping[str, int]
    company_class_counts: Mapping[CompanyDateCoverageClass, int]
    company_class_percentages: Mapping[CompanyDateCoverageClass, float]
    listing_count: int
    valid_identity_count: int
    valid_url_count: int
    listing_counts: EvidenceCounts
    listing_percentages: Mapping[str, float]
    decision_counts: DecisionCounts
    first_seen_available_count: int
    by_adapter: Mapping[str, AdapterRecencySummary]
    companies: tuple[CompanyRecencyRecord, ...]

    @property
    def healthy(self) -> bool:
        return all(
            record.outcome in {AdapterOutcome.SUCCESS.value, AdapterOutcome.EMPTY.value}
            for record in self.companies
        )

    def as_json(self) -> dict[str, object]:
        """Return a JSON-safe representation without descriptions or response bodies."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "scan_at": self.scan_at,
            "boundary": self.boundary,
            "window_days": self.window_days,
            "source_retry_count": self.source_retry_count,
            "registry_version": self.registry_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "enabled_company_count": self.enabled_company_count,
            "outcome_counts": dict(self.outcome_counts),
            "company_class_counts": _enum_counts(self.company_class_counts),
            "company_class_percentages": _enum_percentages(self.company_class_percentages),
            "listing_count": self.listing_count,
            "valid_identity_count": self.valid_identity_count,
            "valid_url_count": self.valid_url_count,
            "listing_counts": asdict(self.listing_counts),
            "listing_percentages": dict(self.listing_percentages),
            "decision_counts": asdict(self.decision_counts),
            "first_seen_available_count": self.first_seen_available_count,
            "by_adapter": {key: _adapter_as_json(value) for key, value in self.by_adapter.items()},
            "companies": [_company_as_json(record) for record in self.companies],
        }


@dataclass(frozen=True, slots=True)
class _PendingCompanyRecord:
    company_id: str
    company_name: str
    source_rank: int
    priority: str
    adapter_type: str
    outcome: str
    complete: bool
    attempt_count: int
    page_count: int
    valid_identity_count: int
    valid_url_count: int
    exception_categories: tuple[str, ...]
    normalized_jobs: tuple[NormalizedJob, ...]
    publication_date_verified: bool


def measure_enabled_recency(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    *,
    scan_at: datetime | None = None,
    generated_at: datetime | None = None,
    source_retry_count: int = 2,
) -> RecencyVerificationReport:
    """List and normalize every enabled source without detail fetches or LLM calls."""
    if scan_at is not None and scan_at.tzinfo is None:
        raise ValueError("scan_at must be timezone-aware")
    if generated_at is not None and generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    if source_retry_count < 0:
        raise ValueError("source_retry_count cannot be negative")

    entries = sorted(
        (entry for entry in registry.entries if entry.source.enabled),
        key=lambda entry: entry.source_rank,
    )
    pending_records: list[_PendingCompanyRecord] = []
    for entry in entries:
        source = entry.source
        result, attempt_count = _list_with_retry(
            adapters.resolve(source),
            source,
            source_retry_count=source_retry_count,
        )
        if result.outcome is AdapterOutcome.SUCCESS:
            normalized_jobs = tuple(
                normalize_job(job, location_policy=profile.location) for job in result.jobs
            )
        else:
            normalized_jobs = ()
        exception_categories = list(
            dict.fromkeys(diagnostic.category for diagnostic in result.diagnostics)
        )
        if attempt_count > 1:
            retry_category = (
                "source_retry_succeeded"
                if result.outcome in {AdapterOutcome.SUCCESS, AdapterOutcome.EMPTY}
                else "source_retry_exhausted"
            )
            exception_categories.insert(0, retry_category)
        pending_records.append(
            _PendingCompanyRecord(
                company_id=source.company_id,
                company_name=source.company_name,
                source_rank=entry.source_rank,
                priority=entry.priority,
                adapter_type=source.adapter_type.value,
                outcome=result.outcome.value,
                complete=result.complete,
                attempt_count=attempt_count,
                page_count=result.page_count,
                valid_identity_count=sum(
                    _has_valid_identity(job, source.identity_strategy) for job in normalized_jobs
                ),
                valid_url_count=len(normalized_jobs),
                exception_categories=tuple(exception_categories),
                normalized_jobs=normalized_jobs,
                publication_date_verified=(
                    source.date_strategy.verified_as_publication
                    and source.date_strategy.basis is DateBasis.PUBLISHED
                ),
            )
        )

    # Use one completion-time boundary for a live run. A listing can be published while a long
    # registry scan is in progress and must not become falsely "future" relative to the start.
    effective_scan_at = scan_at or _local_now()
    timestamp = generated_at or effective_scan_at
    observations_by_company: dict[str, tuple[ListingDateObservation, ...]] = {}
    coverage_inputs: list[CompanyDateCoverageInput] = []
    for pending in pending_records:
        observations = tuple(
            _observation(
                job,
                publication_date_verified=(
                    pending.publication_date_verified and job.date_basis is DateBasis.PUBLISHED
                ),
                profile=profile,
                scan_at=effective_scan_at,
            )
            for job in pending.normalized_jobs
        )
        observations_by_company[pending.company_id] = observations
        coverage_inputs.append(
            CompanyDateCoverageInput(
                company_id=pending.company_id,
                company_name=pending.company_name,
                adapter_type=pending.adapter_type,
                assessment=_source_assessment(pending.outcome),
                observations=observations,
            )
        )

    coverage = build_date_coverage_report(coverage_inputs)
    coverage_by_company = {company.company_id: company for company in coverage.companies}
    records = tuple(
        _complete_company_record(
            pending,
            coverage_by_company[pending.company_id],
            observations_by_company[pending.company_id],
        )
        for pending in pending_records
    )
    adapter_summaries = _adapter_summaries(records)
    outcomes = Counter(record.outcome for record in records)
    return RecencyVerificationReport(
        schema_version=1,
        generated_at=timestamp.isoformat(timespec="seconds"),
        scan_at=effective_scan_at.isoformat(timespec="seconds"),
        boundary=(effective_scan_at - timedelta(days=profile.recency_window_days)).isoformat(
            timespec="seconds"
        ),
        window_days=profile.recency_window_days,
        source_retry_count=source_retry_count,
        registry_version=registry.registry_version,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        profile_hash=profile.content_hash,
        enabled_company_count=len(records),
        outcome_counts=dict(sorted(outcomes.items())),
        company_class_counts=coverage.company_class_counts,
        company_class_percentages=coverage.company_class_percentages,
        listing_count=sum(record.listing_count for record in records),
        valid_identity_count=sum(record.valid_identity_count for record in records),
        valid_url_count=sum(record.valid_url_count for record in records),
        listing_counts=coverage.listing_counts,
        listing_percentages=coverage.listing_percentages,
        decision_counts=coverage.decision_counts,
        first_seen_available_count=coverage.first_seen_available_count,
        by_adapter=adapter_summaries,
        companies=records,
    )


def write_recency_report(report: RecencyVerificationReport, path: Path) -> None:
    """Write sanitized date evidence and public URLs to an ignored report path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _list_with_retry(
    adapter: JobSourceAdapter,
    source: CompanySource,
    *,
    source_retry_count: int,
) -> tuple[AdapterResult, int]:
    retryable_outcomes = {
        AdapterOutcome.PARTIAL,
        AdapterOutcome.FAILED,
        AdapterOutcome.SUSPICIOUS,
    }
    result = adapter.list_jobs(source)
    attempt_count = 1
    while result.outcome in retryable_outcomes and attempt_count <= source_retry_count:
        result = adapter.list_jobs(source)
        attempt_count += 1
    return result, attempt_count


def _observation(
    job: NormalizedJob,
    *,
    publication_date_verified: bool,
    profile: SearchProfile,
    scan_at: datetime,
) -> ListingDateObservation:
    assessment = assess_listing_recency(
        job.published_at,
        raw_date_text=job.published_at_raw,
        basis=job.date_basis,
        scan_at=scan_at,
        window_days=profile.recency_window_days,
        uncertainty_mode=profile.date_uncertainty_mode,
        publication_date_verified=publication_date_verified,
    )
    return ListingDateObservation(
        company_id=job.company_id,
        adapter_type=job.source_type,
        evidence_status=assessment.evidence_status,
        date_basis=job.date_basis,
        raw_date_text=job.published_at_raw,
        job_url=job.canonical_url,
        first_seen_at=None,
        decision=assessment.decision,
        reason=assessment.reason,
        normalized_date=_normalized_date(job.published_at),
    )


def _normalized_date(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _has_valid_identity(job: NormalizedJob, strategy: IdentityStrategy) -> bool:
    if strategy is IdentityStrategy.EXTERNAL_ID:
        return bool(job.external_job_id and job.external_job_id.strip())
    return bool(job.canonical_url)


def _complete_company_record(
    pending: _PendingCompanyRecord,
    coverage: CompanyDateCoverage,
    observations: tuple[ListingDateObservation, ...],
) -> CompanyRecencyRecord:
    return CompanyRecencyRecord(
        company_id=pending.company_id,
        company_name=pending.company_name,
        source_rank=pending.source_rank,
        priority=pending.priority,
        adapter_type=pending.adapter_type,
        outcome=pending.outcome,
        complete=pending.complete,
        attempt_count=pending.attempt_count,
        page_count=pending.page_count,
        listing_count=len(observations),
        valid_identity_count=pending.valid_identity_count,
        valid_url_count=pending.valid_url_count,
        coverage_class=coverage.coverage_class,
        listing_counts=coverage.listing_counts,
        decision_counts=coverage.decision_counts,
        first_seen_available_count=coverage.first_seen_available_count,
        exception_categories=pending.exception_categories,
        observations=observations,
    )


def _source_assessment(outcome: str) -> SourceAssessment:
    if outcome == AdapterOutcome.SUCCESS.value:
        return SourceAssessment.OBSERVED
    if outcome == AdapterOutcome.EMPTY.value:
        return SourceAssessment.NO_LISTINGS
    return SourceAssessment.UNASSESSED


def _adapter_summaries(
    records: tuple[CompanyRecencyRecord, ...],
) -> Mapping[str, AdapterRecencySummary]:
    grouped: dict[str, list[CompanyRecencyRecord]] = defaultdict(list)
    for record in records:
        grouped[record.adapter_type].append(record)
    summaries: dict[str, AdapterRecencySummary] = {}
    for adapter_type, adapter_records in sorted(grouped.items()):
        summaries[adapter_type] = AdapterRecencySummary(
            adapter_type=adapter_type,
            company_count=len(adapter_records),
            outcome_counts=dict(sorted(Counter(item.outcome for item in adapter_records).items())),
            company_class_counts={
                coverage_class: sum(
                    item.coverage_class is coverage_class for item in adapter_records
                )
                for coverage_class in CompanyDateCoverageClass
            },
            listing_count=sum(item.listing_count for item in adapter_records),
            valid_identity_count=sum(item.valid_identity_count for item in adapter_records),
            valid_url_count=sum(item.valid_url_count for item in adapter_records),
            listing_counts=_sum_evidence_counts(item.listing_counts for item in adapter_records),
            decision_counts=_sum_decision_counts(item.decision_counts for item in adapter_records),
            first_seen_available_count=sum(
                item.first_seen_available_count for item in adapter_records
            ),
        )
    return summaries


def _sum_evidence_counts(values: Iterable[EvidenceCounts]) -> EvidenceCounts:
    items = tuple(values)
    return EvidenceCounts(
        reliable=sum(item.reliable for item in items),
        uncertain=sum(item.uncertain for item in items),
        invalid=sum(item.invalid for item in items),
        missing=sum(item.missing for item in items),
    )


def _sum_decision_counts(values: Iterable[DecisionCounts]) -> DecisionCounts:
    items = tuple(values)
    return DecisionCounts(
        inside_window=sum(item.inside_window for item in items),
        outside_window=sum(item.outside_window for item in items),
        uncertain=sum(item.uncertain for item in items),
        invalid=sum(item.invalid for item in items),
    )


def _enum_counts(
    values: Mapping[CompanyDateCoverageClass, int],
) -> dict[str, int]:
    return {key.value: value for key, value in values.items()}


def _enum_percentages(
    values: Mapping[CompanyDateCoverageClass, float],
) -> dict[str, float]:
    return {key.value: value for key, value in values.items()}


def _adapter_as_json(summary: AdapterRecencySummary) -> dict[str, object]:
    return {
        "adapter_type": summary.adapter_type,
        "company_count": summary.company_count,
        "outcome_counts": dict(summary.outcome_counts),
        "company_class_counts": _enum_counts(summary.company_class_counts),
        "listing_count": summary.listing_count,
        "valid_identity_count": summary.valid_identity_count,
        "valid_url_count": summary.valid_url_count,
        "listing_counts": asdict(summary.listing_counts),
        "decision_counts": asdict(summary.decision_counts),
        "first_seen_available_count": summary.first_seen_available_count,
    }


def _company_as_json(record: CompanyRecencyRecord) -> dict[str, object]:
    return {
        "company_id": record.company_id,
        "company_name": record.company_name,
        "source_rank": record.source_rank,
        "priority": record.priority,
        "adapter_type": record.adapter_type,
        "outcome": record.outcome,
        "complete": record.complete,
        "attempt_count": record.attempt_count,
        "page_count": record.page_count,
        "listing_count": record.listing_count,
        "valid_identity_count": record.valid_identity_count,
        "valid_url_count": record.valid_url_count,
        "coverage_class": record.coverage_class.value,
        "listing_counts": asdict(record.listing_counts),
        "decision_counts": asdict(record.decision_counts),
        "first_seen_available_count": record.first_seen_available_count,
        "exception_categories": list(record.exception_categories),
        "observations": [_observation_as_json(item) for item in record.observations],
    }


def _observation_as_json(observation: ListingDateObservation) -> dict[str, object]:
    return {
        "evidence_status": observation.evidence_status.value,
        "date_basis": observation.date_basis.value,
        "raw_date_text": observation.raw_date_text,
        "normalized_date": observation.normalized_date,
        "decision": observation.decision.value,
        "interpretation": observation.reason,
        "job_url": observation.job_url,
        "first_seen_at": (
            observation.first_seen_at.isoformat() if observation.first_seen_at is not None else None
        ),
    }
