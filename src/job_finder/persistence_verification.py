"""Two-pass full-registry validation of durable job identity behavior."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from job_finder.adapters.base import AdapterRegistry
from job_finder.core.company_registry import CompanySourceRegistry
from job_finder.core.search_profile import SearchProfile
from job_finder.filter_verification import (
    FilterVerificationReport,
    FinalFilterDecision,
    verify_filters,
)
from job_finder.persistence.database import migrated_database
from job_finder.persistence.locking import ScanLock
from job_finder.persistence.repository import JobStateRepository


@dataclass(frozen=True, slots=True)
class NewIdentityRecord:
    """Sanitized evidence for an identity first seen during one validation pass."""

    job_key: str
    company_id: str
    title: str
    canonical_url: str


@dataclass(frozen=True, slots=True)
class PersistencePassRecord:
    """Identity counts observed during one complete collection and filter pass."""

    pass_number: int
    scan_at: str
    source_healthy: bool
    listing_count: int
    retained_count: int
    observed_identity_count: int
    new_identity_count: int
    existing_identity_count: int
    new_identities: tuple[NewIdentityRecord, ...]


@dataclass(frozen=True, slots=True)
class PersistenceVerificationReport:
    """Phase 7 two-pass validation report."""

    schema_version: int
    generated_at: str
    registry_version: str
    profile_version: str
    profile_hash: str
    initial_identity_count: int
    final_identity_count: int
    passes: tuple[PersistencePassRecord, ...]

    @property
    def healthy(self) -> bool:
        return (
            len(self.passes) == 2
            and all(item.source_healthy for item in self.passes)
            and self.passes[1].new_identity_count == 0
        )

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "registry_version": self.registry_version,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "initial_identity_count": self.initial_identity_count,
            "final_identity_count": self.final_identity_count,
            "healthy": self.healthy,
            "passes": [
                {
                    **asdict(item),
                    "new_identities": [asdict(identity) for identity in item.new_identities],
                }
                for item in self.passes
            ],
        }


def verify_persistence(
    registry: CompanySourceRegistry,
    adapters: AdapterRegistry,
    profile: SearchProfile,
    *,
    database_path: Path,
    lock_path: Path,
    source_retry_count: int = 2,
    require_empty: bool = True,
) -> PersistenceVerificationReport:
    """Run the complete filtered pipeline twice and compare stable identities."""
    pass_records: list[PersistencePassRecord] = []
    with ScanLock(lock_path), migrated_database(database_path) as connection:
        repository = JobStateRepository(connection)
        initial_count = repository.count()
        if require_empty and initial_count:
            raise ValueError(
                "persistence validation requires a fresh database; "
                f"found {initial_count} existing identities"
            )
        for pass_number in (1, 2):
            filter_report = verify_filters(
                registry,
                adapters,
                profile,
                source_retry_count=source_retry_count,
            )
            pass_records.append(
                persist_retained_candidates(
                    filter_report,
                    repository,
                    pass_number=pass_number,
                )
            )
        final_count = repository.count()
    return PersistenceVerificationReport(
        schema_version=1,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        registry_version=registry.registry_version,
        profile_version=profile.version,
        profile_hash=profile.content_hash,
        initial_identity_count=initial_count,
        final_identity_count=final_count,
        passes=tuple(pass_records),
    )


def persist_retained_candidates(
    report: FilterVerificationReport,
    repository: JobStateRepository,
    *,
    pass_number: int,
) -> PersistencePassRecord:
    """Observe every retained candidate and report which stable identities were new."""
    observed_at = datetime.fromisoformat(report.scan_at)
    if observed_at.tzinfo is None:
        raise ValueError("filter report scan_at must be timezone-aware")
    retained = [
        row for row in report.listings if row.final_decision is FinalFilterDecision.RETAINED
    ]
    new_identities: list[NewIdentityRecord] = []
    for row in retained:
        observation = repository.observe_listing(
            row.normalized_job,
            observed_at=observed_at,
            profile_version=report.profile_version,
        )
        if observation.is_new:
            new_identities.append(
                NewIdentityRecord(
                    job_key=observation.record.job_key,
                    company_id=row.company_id,
                    title=row.title_original,
                    canonical_url=observation.record.canonical_url,
                )
            )
    return PersistencePassRecord(
        pass_number=pass_number,
        scan_at=report.scan_at,
        source_healthy=report.healthy,
        listing_count=report.listing_count,
        retained_count=len(retained),
        observed_identity_count=len(retained),
        new_identity_count=len(new_identities),
        existing_identity_count=len(retained) - len(new_identities),
        new_identities=tuple(new_identities),
    )


def write_persistence_report(report: PersistenceVerificationReport, path: Path) -> None:
    """Write the sanitized Phase 7 validation report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def second_pass_new_companies(report: PersistenceVerificationReport) -> Mapping[str, int]:
    """Summarize second-pass new identities by company for investigation."""
    counts: dict[str, int] = {}
    if len(report.passes) < 2:
        return counts
    for item in report.passes[1].new_identities:
        counts[item.company_id] = counts.get(item.company_id, 0) + 1
    return dict(sorted(counts.items()))
