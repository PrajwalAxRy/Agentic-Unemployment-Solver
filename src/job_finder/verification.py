"""Read-only adapter verification and sanitized coverage reporting."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.job_contracts import DateBasis
from job_finder.core.source_contracts import AdapterOutcome, AdapterType


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
    sample_job_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceVerificationReport:
    """One immutable verification run that never modifies job-history state."""

    schema_version: int
    generated_at: str
    registry_version: str
    adapter_type: str
    company_count: int
    outcome_counts: dict[str, int]
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

    records: list[SourceVerificationRecord] = []
    for entry in entries:
        result = adapters.resolve(entry.source).list_jobs(entry.source)
        dates = Counter(job.date_basis.value for job in result.jobs)
        records.append(
            SourceVerificationRecord(
                company_id=entry.source.company_id,
                company_name=entry.source.company_name,
                source_rank=entry.source_rank,
                priority=entry.priority,
                adapter_type=entry.source.adapter_type.value,
                configuration_version=registry.registry_version,
                outcome=result.outcome.value,
                complete=result.complete,
                job_count=len(result.jobs),
                page_count=result.page_count,
                missing_field_count=sum(
                    diagnostic.category == "malformed_job" for diagnostic in result.diagnostics
                ),
                date_basis_distribution={
                    basis.value: dates.get(basis.value, 0) for basis in DateBasis
                },
                exception_categories=tuple(
                    dict.fromkeys(diagnostic.category for diagnostic in result.diagnostics)
                ),
                sample_job_urls=tuple(job.canonical_url for job in result.jobs[:3]),
            )
        )
    outcomes = Counter(record.outcome for record in records)
    timestamp = generated_at or datetime.now().astimezone()
    return SourceVerificationReport(
        schema_version=1,
        generated_at=timestamp.isoformat(timespec="seconds"),
        registry_version=registry.registry_version,
        adapter_type=adapter_type.value,
        company_count=len(records),
        outcome_counts=dict(sorted(outcomes.items())),
        records=tuple(records),
    )


def write_verification_report(report: SourceVerificationReport, path: Path) -> None:
    """Write only aggregate fields and public sample URLs to an ignored report path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
