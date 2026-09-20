"""Canonical company-seed loading and minimum source-schema accounting."""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from job_finder.core.source_contracts import (
    AdapterType,
    CompanySource,
    company_source_from_mapping,
)

EXPECTED_COMPANY_SEED_COLUMNS = (
    "company_id",
    "company_name",
    "priority",
    "careers_url_hint",
    "source_rank",
)


@dataclass(frozen=True, slots=True)
class CompanySeedRecord:
    """One immutable row from the canonical seed snapshot."""

    company_id: str
    company_name: str
    priority: str
    careers_url_hint: str
    source_rank: int


@dataclass(frozen=True, slots=True)
class MinimumSourceAudit:
    """Phase 1 accounting before Phase 2 source discovery begins."""

    total_companies: int
    unique_company_ids: int
    unique_company_names: int
    unique_source_ranks: int
    priority_counts: dict[str, int]
    missing_official_urls: int
    missing_adapter_types: int
    invalid_configuration: int


def load_company_seed(path: Path) -> tuple[CompanySeedRecord, ...]:
    """Load and strictly validate the canonical company CSV."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != EXPECTED_COMPANY_SEED_COLUMNS:
            raise ValueError(
                "company seed columns must be exactly: " + ", ".join(EXPECTED_COMPANY_SEED_COLUMNS)
            )
        records = tuple(_record_from_row(row, index) for index, row in enumerate(reader, start=2))

    _require_unique(records, "company_id")
    _require_unique(records, "company_name")
    _require_unique(records, "source_rank")
    expected_ranks = tuple(range(1, len(records) + 1))
    actual_ranks = tuple(record.source_rank for record in records)
    if actual_ranks != expected_ranks:
        raise ValueError(
            "company seed source_rank values must be contiguous and preserve row order"
        )
    return records


def minimum_company_source(record: CompanySeedRecord) -> CompanySource:
    """Represent one seed row as an explicit unresolved Phase 1 source record."""
    return company_source_from_mapping(
        {
            "schema_version": 1,
            "company_id": record.company_id,
            "company_name": record.company_name,
            "status": "unresolved",
            "careers_url": None,
            "adapter_type": "unresolved",
            "adapter_parameters": {},
            "identity_strategy": "unresolved",
            "date_strategy": {
                "field_name": None,
                "basis": "unknown",
                "verified_as_publication": False,
                "notes": "Phase 2 source discovery is pending.",
            },
            "detail_strategy": "unresolved",
            "enabled": False,
            "confidence": "unknown",
            "evidence": [record.careers_url_hint],
            "low_confidence_approved": False,
            "exception_reason": None,
            "notes": "careers_url_hint is unverified discovery evidence, not an official source",
        }
    )


def build_minimum_source_audit(records: Iterable[CompanySeedRecord]) -> MinimumSourceAudit:
    """Run every seed row through the minimum company-source schema."""
    items = tuple(records)
    invalid_configuration = 0
    missing_official_urls = 0
    missing_adapter_types = 0
    for record in items:
        try:
            source = minimum_company_source(record)
        except ValueError:
            invalid_configuration += 1
            continue
        if source.careers_url is None:
            missing_official_urls += 1
        if source.adapter_type is AdapterType.UNRESOLVED:
            missing_adapter_types += 1

    priorities = Counter(record.priority for record in items)
    return MinimumSourceAudit(
        total_companies=len(items),
        unique_company_ids=len({record.company_id for record in items}),
        unique_company_names=len({record.company_name for record in items}),
        unique_source_ranks=len({record.source_rank for record in items}),
        priority_counts={key: priorities[key] for key in ("P1", "P2", "P3")},
        missing_official_urls=missing_official_urls,
        missing_adapter_types=missing_adapter_types,
        invalid_configuration=invalid_configuration,
    )


def _record_from_row(row: dict[str, str], line_number: int) -> CompanySeedRecord:
    values: dict[str, str] = {}
    for column in EXPECTED_COMPANY_SEED_COLUMNS:
        value = row.get(column)
        if value is None or not value.strip():
            raise ValueError(f"company seed line {line_number}: {column} must be non-empty")
        values[column] = value.strip()

    if values["priority"] not in {"P1", "P2", "P3"}:
        raise ValueError(f"company seed line {line_number}: invalid priority")
    try:
        source_rank = int(values["source_rank"])
    except ValueError as error:
        raise ValueError(
            f"company seed line {line_number}: source_rank must be an integer"
        ) from error
    if source_rank <= 0:
        raise ValueError(f"company seed line {line_number}: source_rank must be positive")

    parsed_hint = urlsplit(values["careers_url_hint"])
    if parsed_hint.scheme not in {"http", "https"} or not parsed_hint.hostname:
        raise ValueError(f"company seed line {line_number}: careers_url_hint must be an HTTP URL")
    if parsed_hint.username is not None or parsed_hint.password is not None:
        raise ValueError(
            f"company seed line {line_number}: careers_url_hint must not contain credentials"
        )

    return CompanySeedRecord(
        company_id=values["company_id"],
        company_name=values["company_name"],
        priority=values["priority"],
        careers_url_hint=values["careers_url_hint"],
        source_rank=source_rank,
    )


def _require_unique(records: tuple[CompanySeedRecord, ...], field_name: str) -> None:
    values = [getattr(record, field_name) for record in records]
    duplicate_values = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicate_values:
        display = ", ".join(str(value) for value in duplicate_values)
        raise ValueError(f"company seed contains duplicate {field_name} values: {display}")
