"""Validated company-source registry storage and canonical-seed accounting."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from job_finder.core.company_seed import CompanySeedRecord
from job_finder.core.source_contracts import CompanySource, company_source_from_mapping
from job_finder.core.validation import required_string


@dataclass(frozen=True, slots=True)
class CompanyRegistryEntry:
    """One source record plus immutable seed ordering and priority metadata."""

    source_rank: int
    priority: str
    last_verified_at: datetime | None
    source: CompanySource


@dataclass(frozen=True, slots=True)
class CompanySourceRegistry:
    """Versioned collection of company sources used by runtime scans."""

    schema_version: int
    registry_version: str
    generated_at: datetime
    discovery_batch_id: str
    entries: tuple[CompanyRegistryEntry, ...]


@dataclass(frozen=True, slots=True)
class RegistryAudit:
    """Full accounting of the registry against the canonical seed."""

    seed_total: int
    registry_total: int
    missing_company_ids: tuple[str, ...]
    extra_company_ids: tuple[str, ...]
    name_mismatches: tuple[str, ...]
    priority_mismatches: tuple[str, ...]
    source_rank_mismatches: tuple[str, ...]
    by_status: Mapping[str, int]
    by_adapter: Mapping[str, int]
    by_confidence: Mapping[str, int]
    enabled_count: int

    @property
    def reconciled(self) -> bool:
        """Whether every canonical company appears exactly once with matching metadata."""
        return not (
            self.missing_company_ids
            or self.extra_company_ids
            or self.name_mismatches
            or self.priority_mismatches
            or self.source_rank_mismatches
        )


def load_company_registry(path: Path) -> CompanySourceRegistry:
    """Load and validate the versioned JSON company-source registry."""
    with path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("company registry must be a JSON object")
    schema_version = _required_int(raw, "schema_version", "registry")
    if schema_version != 1:
        raise ValueError(f"unsupported registry schema_version: {schema_version}; supported=1")
    generated_at = _timestamp(raw.get("generated_at"), "registry.generated_at", nullable=False)
    if generated_at is None:  # pragma: no cover - narrowed by nullable=False
        raise AssertionError("generated_at unexpectedly absent")

    sources_raw = raw.get("sources")
    if not isinstance(sources_raw, list):
        raise ValueError("registry.sources must be an array")
    entries = tuple(
        _entry_from_mapping(_as_mapping(item, f"registry.sources[{index}]"))
        for index, item in enumerate(sources_raw)
    )
    verified_after_generation = [
        entry.source.company_id
        for entry in entries
        if entry.last_verified_at is not None and entry.last_verified_at > generated_at
    ]
    if verified_after_generation:
        raise ValueError(
            "registry source.last_verified_at cannot be later than registry.generated_at: "
            + ", ".join(verified_after_generation)
        )
    company_ids = [entry.source.company_id for entry in entries]
    if len(company_ids) != len(set(company_ids)):
        raise ValueError("company registry contains duplicate company IDs")

    return CompanySourceRegistry(
        schema_version=schema_version,
        registry_version=required_string(raw, "registry_version", "registry"),
        generated_at=generated_at,
        discovery_batch_id=required_string(raw, "discovery_batch_id", "registry"),
        entries=entries,
    )


def audit_company_registry(
    registry: CompanySourceRegistry,
    seed_records: Iterable[CompanySeedRecord],
) -> RegistryAudit:
    """Reconcile a registry to all canonical companies and summarize coverage."""
    seed = tuple(seed_records)
    seed_by_id = {record.company_id: record for record in seed}
    entries_by_id = {entry.source.company_id: entry for entry in registry.entries}
    missing = tuple(sorted(set(seed_by_id) - set(entries_by_id)))
    extra = tuple(sorted(set(entries_by_id) - set(seed_by_id)))
    shared = set(seed_by_id) & set(entries_by_id)

    def mismatches(predicate: object) -> tuple[str, ...]:
        if not callable(predicate):  # pragma: no cover - internal misuse guard
            raise TypeError("predicate must be callable")
        return tuple(sorted(company_id for company_id in shared if predicate(company_id)))

    names = mismatches(
        lambda company_id: (
            seed_by_id[company_id].company_name != entries_by_id[company_id].source.company_name
        )
    )
    priorities = mismatches(
        lambda company_id: seed_by_id[company_id].priority != entries_by_id[company_id].priority
    )
    ranks = mismatches(
        lambda company_id: (
            seed_by_id[company_id].source_rank != entries_by_id[company_id].source_rank
        )
    )
    statuses = Counter(entry.source.status.value for entry in registry.entries)
    adapters = Counter(entry.source.adapter_type.value for entry in registry.entries)
    confidences = Counter(entry.source.confidence.value for entry in registry.entries)
    return RegistryAudit(
        seed_total=len(seed),
        registry_total=len(registry.entries),
        missing_company_ids=missing,
        extra_company_ids=extra,
        name_mismatches=names,
        priority_mismatches=priorities,
        source_rank_mismatches=ranks,
        by_status=dict(sorted(statuses.items())),
        by_adapter=dict(sorted(adapters.items())),
        by_confidence=dict(sorted(confidences.items())),
        enabled_count=sum(entry.source.enabled for entry in registry.entries),
    )


def _entry_from_mapping(raw: Mapping[str, object]) -> CompanyRegistryEntry:
    priority = required_string(raw, "priority", "registry source")
    if priority not in {"P1", "P2", "P3"}:
        raise ValueError("registry source.priority must be one of: P1, P2, P3")
    source_rank = _required_int(raw, "source_rank", "registry source")
    if source_rank <= 0:
        raise ValueError("registry source.source_rank must be positive")
    last_verified_at = _timestamp(
        raw.get("last_verified_at"),
        "registry source.last_verified_at",
        nullable=True,
    )
    return CompanyRegistryEntry(
        source_rank=source_rank,
        priority=priority,
        last_verified_at=last_verified_at,
        source=company_source_from_mapping(raw),
    )


def _timestamp(value: object, path: str, *, nullable: bool) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        qualifier = "null or " if nullable else ""
        raise ValueError(f"{path} must be {qualifier}an ISO-8601 timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{path} must be an ISO-8601 timestamp") from error
    if result.tzinfo is None:
        raise ValueError(f"{path} must be timezone-aware")
    return result


def _as_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _required_int(raw: Mapping[str, object], key: str, path: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be an integer")
    return value
