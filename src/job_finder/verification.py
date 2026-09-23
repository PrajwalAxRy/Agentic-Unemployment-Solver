"""Read-only adapter verification and sanitized coverage reporting."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from job_finder.adapters.base import (
    AdapterConfigurationError,
    AdapterRegistry,
    list_jobs_with_retry,
)
from job_finder.core.company_registry import CompanyRegistryEntry, CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterType,
    DiagnosticSeverity,
)

_COLLAPSE_MINIMUM_BASELINE_COUNT = 20
_COLLAPSE_RATIO = 0.20
_FUTURE_DATE_TOLERANCE = timedelta(days=1)
_STALE_DATE_AGE = timedelta(days=365)
_STALE_DATE_MINIMUM_COUNT = 5


class FailureCategory(StrEnum):
    """Stable Phase 10 failure categories used across adapter families."""

    TEMPORARY_AVAILABILITY = "temporary_availability"
    RATE_LIMIT = "rate_limit"
    CONFIGURATION_ERROR = "configuration_error"
    SOURCE_MOVED = "source_moved"
    SCHEMA_CHANGE = "schema_change"
    PARSER_DEFECT = "parser_defect"
    ACCESS_RESTRICTION = "access_restriction"
    UNSUPPORTED_SOURCE = "unsupported_source"


class SourceAnomaly(StrEnum):
    """Cross-adapter conditions that must not be reported as healthy source results."""

    RESULT_COUNT_COLLAPSE = "result_count_collapse"
    FUTURE_PUBLICATION_DATE = "future_publication_date"
    STALE_PUBLICATION_DATES = "stale_publication_dates"


@dataclass(frozen=True, slots=True)
class VerificationBaseline:
    """Minimal sanitized history needed for result-count anomaly detection."""

    generated_at: str
    job_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class SourceVerificationRecord:
    """Sanitized health summary for one company source."""

    company_id: str
    company_name: str
    source_rank: int
    priority: str
    adapter_type: str
    configuration_version: str
    outcome: str
    complete: bool
    job_count: int
    page_count: int
    missing_field_count: int
    date_basis_distribution: dict[str, int]
    exception_categories: tuple[str, ...]
    failure_categories: tuple[str, ...]
    anomaly_categories: tuple[str, ...]
    attempt_count: int
    sample_job_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceVerificationReport:
    """One immutable verification run that never modifies job-history state."""

    schema_version: int
    generated_at: str
    registry_version: str
    adapter_type: str
    baseline_generated_at: str | None
    company_count: int
    outcome_counts: dict[str, int]
    failure_category_counts: dict[str, int]
    anomaly_counts: dict[str, int]
    records: tuple[SourceVerificationRecord, ...]

    @property
    def healthy(self) -> bool:
        return all(
            record.outcome in {AdapterOutcome.SUCCESS.value, AdapterOutcome.EMPTY.value}
            for record in self.records
        )

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def verify_adapter_sources(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    adapter_type: AdapterType,
    *,
    company_ids: Iterable[str] = (),
    generated_at: datetime | None = None,
    baseline: VerificationBaseline | None = None,
    source_retry_count: int = 0,
) -> SourceVerificationReport:
    """Run a bounded listing check for every selected source in one adapter family."""
    requested_ids = tuple(company_ids)
    requested_set = set(requested_ids)
    if len(requested_ids) != len(requested_set):
        raise ValueError("company_ids must not contain duplicates")

    family_entries = [
        entry for entry in registry.entries if entry.source.adapter_type is adapter_type
    ]
    family_ids = {entry.source.company_id for entry in family_entries}
    unknown = sorted(requested_set - family_ids)
    if unknown:
        raise ValueError(
            f"company_ids are not configured for adapter {adapter_type.value}: "
            + ", ".join(unknown)
        )
    entries = [
        entry
        for entry in family_entries
        if not requested_set or entry.source.company_id in requested_set
    ]
    entries.sort(key=lambda item: item.source_rank)

    return _verify_entries(
        registry,
        adapters,
        entries,
        adapter_type=adapter_type.value,
        generated_at=generated_at,
        baseline=baseline,
        source_retry_count=source_retry_count,
    )


def verify_enabled_sources(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    *,
    generated_at: datetime | None = None,
    baseline: VerificationBaseline | None = None,
    source_retry_count: int = 0,
) -> SourceVerificationReport:
    """Run one listing verification across every enabled source in registry order."""
    entries = [entry for entry in registry.entries if entry.source.enabled]
    entries.sort(key=lambda item: item.source_rank)
    return _verify_entries(
        registry,
        adapters,
        entries,
        adapter_type="all_enabled",
        generated_at=generated_at,
        baseline=baseline,
        source_retry_count=source_retry_count,
    )


def _verify_entries(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    entries: list[CompanyRegistryEntry],
    *,
    adapter_type: str,
    generated_at: datetime | None,
    baseline: VerificationBaseline | None,
    source_retry_count: int,
) -> SourceVerificationReport:
    if source_retry_count < 0:
        raise ValueError("source_retry_count cannot be negative")
    timestamp = generated_at or datetime.now().astimezone()
    if timestamp.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    records: list[SourceVerificationRecord] = []
    for entry in entries:
        try:
            adapter = adapters.resolve(entry.source)
            result, attempt_count = list_jobs_with_retry(
                adapter,
                entry.source,
                retry_count=source_retry_count,
            )
        except AdapterConfigurationError:
            records.append(
                _exception_record(
                    entry,
                    registry,
                    category=FailureCategory.CONFIGURATION_ERROR,
                    exception_category="configuration_error",
                )
            )
            continue
        except Exception:  # noqa: BLE001 - one broken adapter must not hide healthy peers.
            records.append(
                _exception_record(
                    entry,
                    registry,
                    category=FailureCategory.PARSER_DEFECT,
                    exception_category="unexpected_adapter_error",
                )
            )
            continue

        dates = Counter(job.date_basis.value for job in result.jobs)
        anomalies = _source_anomalies(
            result.jobs,
            current_count=len(result.jobs),
            previous_count=(
                baseline.job_counts.get(entry.source.company_id) if baseline is not None else None
            ),
            generated_at=timestamp,
            result_outcome=result.outcome,
        )
        outcome = AdapterOutcome.SUSPICIOUS if anomalies else result.outcome
        complete = False if anomalies else result.complete
        failures = set(_failure_categories(result.diagnostics, outcome=result.outcome))
        if anomalies:
            failures.add(FailureCategory.SCHEMA_CHANGE)
        exceptions = list(dict.fromkeys(item.category for item in result.diagnostics))
        exceptions.extend(item.value for item in anomalies if item.value not in exceptions)
        records.append(
            SourceVerificationRecord(
                company_id=entry.source.company_id,
                company_name=entry.source.company_name,
                source_rank=entry.source_rank,
                priority=entry.priority,
                adapter_type=entry.source.adapter_type.value,
                configuration_version=registry.registry_version,
                outcome=outcome.value,
                complete=complete,
                job_count=len(result.jobs),
                page_count=result.page_count,
                missing_field_count=sum(
                    diagnostic.category
                    in {"malformed_job", "missing_description", "missing_location"}
                    for diagnostic in result.diagnostics
                ),
                date_basis_distribution={
                    basis.value: dates.get(basis.value, 0) for basis in DateBasis
                },
                exception_categories=tuple(exceptions),
                failure_categories=tuple(sorted(item.value for item in failures)),
                anomaly_categories=tuple(item.value for item in anomalies),
                attempt_count=attempt_count,
                sample_job_urls=tuple(job.canonical_url for job in result.jobs[:3]),
            )
        )
    outcomes = Counter(record.outcome for record in records)
    failure_counts = Counter(
        category for record in records for category in record.failure_categories
    )
    anomaly_counts = Counter(
        category for record in records for category in record.anomaly_categories
    )
    return SourceVerificationReport(
        schema_version=2,
        generated_at=timestamp.isoformat(timespec="seconds"),
        registry_version=registry.registry_version,
        adapter_type=adapter_type,
        baseline_generated_at=baseline.generated_at if baseline is not None else None,
        company_count=len(records),
        outcome_counts=dict(sorted(outcomes.items())),
        failure_category_counts=dict(sorted(failure_counts.items())),
        anomaly_counts=dict(sorted(anomaly_counts.items())),
        records=tuple(records),
    )


def load_verification_baseline(path: Path) -> VerificationBaseline:
    """Load only prior aggregate counts; ignore all other generated-report content."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load verification baseline: {path}") from error
    if not isinstance(raw, dict):
        raise ValueError("verification baseline must be a JSON object")
    generated_at = raw.get("generated_at")
    records = raw.get("records")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise ValueError("verification baseline generated_at must be a non-empty string")
    if not isinstance(records, list):
        raise ValueError("verification baseline records must be an array")
    counts: dict[str, int] = {}
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ValueError(f"verification baseline records[{index}] must be an object")
        company_id = item.get("company_id")
        job_count = item.get("job_count")
        if not isinstance(company_id, str) or not company_id.strip():
            raise ValueError(f"verification baseline records[{index}].company_id must be non-empty")
        if company_id in counts:
            raise ValueError(f"verification baseline has duplicate company_id: {company_id}")
        if not isinstance(job_count, int) or isinstance(job_count, bool) or job_count < 0:
            raise ValueError(
                f"verification baseline records[{index}].job_count must be non-negative"
            )
        counts[company_id] = job_count
    return VerificationBaseline(generated_at=generated_at, job_counts=counts)


def _exception_record(
    entry: CompanyRegistryEntry,
    registry: CompanySourceRegistry,
    *,
    category: FailureCategory,
    exception_category: str,
) -> SourceVerificationRecord:
    return SourceVerificationRecord(
        company_id=entry.source.company_id,
        company_name=entry.source.company_name,
        source_rank=entry.source_rank,
        priority=entry.priority,
        adapter_type=entry.source.adapter_type.value,
        configuration_version=registry.registry_version,
        outcome=AdapterOutcome.FAILED.value,
        complete=False,
        job_count=0,
        page_count=0,
        missing_field_count=0,
        date_basis_distribution={basis.value: 0 for basis in DateBasis},
        exception_categories=(exception_category,),
        failure_categories=(category.value,),
        anomaly_categories=(),
        attempt_count=1,
        sample_job_urls=(),
    )


def _source_anomalies(
    jobs: tuple[NormalizedJob, ...],
    *,
    current_count: int,
    previous_count: int | None,
    generated_at: datetime,
    result_outcome: AdapterOutcome,
) -> tuple[SourceAnomaly, ...]:
    anomalies: list[SourceAnomaly] = []
    if (
        result_outcome in {AdapterOutcome.SUCCESS, AdapterOutcome.EMPTY}
        and previous_count is not None
        and previous_count >= _COLLAPSE_MINIMUM_BASELINE_COUNT
        and current_count <= previous_count * _COLLAPSE_RATIO
    ):
        anomalies.append(SourceAnomaly.RESULT_COUNT_COLLAPSE)

    reliable_dates = [
        job.published_at
        for job in jobs
        if job.date_basis is DateBasis.PUBLISHED and job.published_at is not None
    ]
    if any(_is_future(value, generated_at) for value in reliable_dates):
        anomalies.append(SourceAnomaly.FUTURE_PUBLICATION_DATE)
    if len(reliable_dates) >= _STALE_DATE_MINIMUM_COUNT and all(
        _is_stale(value, generated_at) for value in reliable_dates
    ):
        anomalies.append(SourceAnomaly.STALE_PUBLICATION_DATES)
    return tuple(anomalies)


def _is_future(value: datetime | date, generated_at: datetime) -> bool:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return True
        return value > generated_at + _FUTURE_DATE_TOLERANCE
    return value > (generated_at + _FUTURE_DATE_TOLERANCE).date()


def _is_stale(value: datetime | date, generated_at: datetime) -> bool:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return True
        return value < generated_at - _STALE_DATE_AGE
    return value < (generated_at - _STALE_DATE_AGE).date()


def _failure_categories(
    diagnostics: tuple[AdapterDiagnostic, ...],
    *,
    outcome: AdapterOutcome,
) -> tuple[FailureCategory, ...]:
    categories: set[FailureCategory] = set()
    for diagnostic in diagnostics:
        if diagnostic.severity is not DiagnosticSeverity.ERROR:
            continue
        category = _classify_diagnostic(diagnostic)
        if category is not None:
            categories.add(category)
    if outcome not in {AdapterOutcome.SUCCESS, AdapterOutcome.EMPTY} and not categories:
        categories.add(FailureCategory.PARSER_DEFECT)
    return tuple(sorted(categories, key=lambda item: item.value))


def _classify_diagnostic(diagnostic: AdapterDiagnostic) -> FailureCategory | None:
    raw = diagnostic.category
    status = _status_code(diagnostic.context)
    if raw == "access_block" or status in {401, 403}:
        return FailureCategory.ACCESS_RESTRICTION
    if status == 429:
        return FailureCategory.RATE_LIMIT
    if raw in {"timeout", "network_error", "response_too_large"}:
        return FailureCategory.TEMPORARY_AVAILABILITY
    if raw == "http_error":
        if status in {404, 410}:
            return FailureCategory.SOURCE_MOVED
        if status is not None and 500 <= status <= 599:
            return FailureCategory.TEMPORARY_AVAILABILITY
        return FailureCategory.CONFIGURATION_ERROR
    if raw in {"redirect_limit", "unexpected_redirect"}:
        return FailureCategory.SOURCE_MOVED
    if raw in {
        "invalid_content_type",
        "invalid_html",
        "invalid_json",
        "unsupported_schema",
    }:
        return FailureCategory.SCHEMA_CHANGE
    if diagnostic.severity is DiagnosticSeverity.ERROR:
        return FailureCategory.PARSER_DEFECT
    return None


def _status_code(context: Mapping[str, str]) -> int | None:
    raw = context.get("status_code")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def write_verification_report(report: SourceVerificationReport, path: Path) -> None:
    """Write only aggregate fields and public sample URLs to an ignored report path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
