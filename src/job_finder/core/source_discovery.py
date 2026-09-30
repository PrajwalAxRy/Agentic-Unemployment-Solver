"""Provisional source-discovery format, validation, and guarded registry import."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from job_finder.core.company_seed import CompanySeedRecord
from job_finder.core.job_contracts import DateBasis
from job_finder.core.source_contracts import (
    AdapterType,
    CompanySource,
    Confidence,
    DetailStrategy,
    IdentityStrategy,
    company_source_from_mapping,
)
from job_finder.core.validation import required_string


class DiscoveryStatus(StrEnum):
    """Review state of an automated discovery proposal."""

    UNRESOLVED = "unresolved"
    PROPOSED = "proposed"
    AUTO_VERIFIED = "auto_verified"
    CONFLICT = "conflict"
    ACCESS_CONCERN = "access_concern"


class ListingMode(StrEnum):
    """How a proposed source exposes its job inventory."""

    UNKNOWN = "unknown"
    COMPLETE_LIST = "complete_list"
    SEARCH_ONLY = "search_only"


@dataclass(frozen=True, slots=True)
class DiscoveryEvidence:
    """One public URL and the fact it supports."""

    url: str
    evidence_type: str
    note: str


@dataclass(frozen=True, slots=True)
class SourceDiscoveryProposal:
    """Non-active proposal for one canonical company's public job source."""

    schema_version: int
    company_id: str
    company_name: str
    source_rank: int
    priority: str
    status: DiscoveryStatus
    official_careers_url: str | None
    regional_board_url: str | None
    adapter_type: AdapterType
    adapter_parameters: Mapping[str, str]
    listing_mode: ListingMode
    list_endpoint: str | None
    pagination: str
    external_job_id_field: str | None
    publication_date_field: str | None
    publication_date_basis: DateBasis
    publication_date_verified: bool
    title_field: str | None
    location_field: str | None
    detail_strategy: DetailStrategy
    confidence: Confidence
    evidence: tuple[DiscoveryEvidence, ...]
    access_concern: str | None
    notes: str


@dataclass(frozen=True, slots=True)
class DiscoveryBatch:
    """Complete proposal batch tied to one canonical seed snapshot."""

    schema_version: int
    batch_id: str
    discovered_at: datetime
    proposals: tuple[SourceDiscoveryProposal, ...]


@dataclass(frozen=True, slots=True)
class DiscoveryAudit:
    """Accounting and coverage metrics for a proposal batch."""

    seed_total: int
    proposal_total: int
    missing_company_ids: tuple[str, ...]
    extra_company_ids: tuple[str, ...]
    name_mismatches: tuple[str, ...]
    source_rank_mismatches: tuple[str, ...]
    by_status: Mapping[str, int]
    by_adapter: Mapping[str, int]
    by_confidence: Mapping[str, int]

    @property
    def reconciled(self) -> bool:
        return not (
            self.missing_company_ids
            or self.extra_company_ids
            or self.name_mismatches
            or self.source_rank_mismatches
        )


def load_discovery_batch(path: Path) -> DiscoveryBatch:
    """Load a JSON discovery batch without treating proposals as active configuration."""
    with path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("source discovery batch must be a JSON object")
    schema_version = _required_int(raw, "schema_version", "batch")
    if schema_version != 1:
        raise ValueError(f"unsupported discovery schema_version: {schema_version}; supported=1")
    discovered_at_raw = required_string(raw, "discovered_at", "batch")
    try:
        discovered_at = datetime.fromisoformat(discovered_at_raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("batch.discovered_at must be an ISO-8601 timestamp") from error
    if discovered_at.tzinfo is None:
        raise ValueError("batch.discovered_at must be timezone-aware")

    proposals_raw = raw.get("proposals")
    if not isinstance(proposals_raw, list):
        raise ValueError("batch.proposals must be an array")
    proposals = tuple(
        _proposal_from_mapping(_as_mapping(item, f"batch.proposals[{index}]"))
        for index, item in enumerate(proposals_raw)
    )
    company_ids = [proposal.company_id for proposal in proposals]
    if len(company_ids) != len(set(company_ids)):
        raise ValueError("source discovery batch contains duplicate company IDs")

    return DiscoveryBatch(
        schema_version=schema_version,
        batch_id=required_string(raw, "batch_id", "batch"),
        discovered_at=discovered_at,
        proposals=proposals,
    )


def audit_discovery_batch(
    batch: DiscoveryBatch,
    seed_records: Iterable[CompanySeedRecord],
) -> DiscoveryAudit:
    """Reconcile proposals to the canonical seed and summarize review coverage."""
    seed = tuple(seed_records)
    seed_by_id = {record.company_id: record for record in seed}
    proposal_by_id = {proposal.company_id: proposal for proposal in batch.proposals}
    missing = tuple(sorted(set(seed_by_id) - set(proposal_by_id)))
    extra = tuple(sorted(set(proposal_by_id) - set(seed_by_id)))
    shared = set(seed_by_id) & set(proposal_by_id)
    name_mismatches = tuple(
        sorted(
            company_id
            for company_id in shared
            if seed_by_id[company_id].company_name != proposal_by_id[company_id].company_name
        )
    )
    rank_mismatches = tuple(
        sorted(
            company_id
            for company_id in shared
            if seed_by_id[company_id].source_rank != proposal_by_id[company_id].source_rank
        )
    )
    statuses = Counter(proposal.status.value for proposal in batch.proposals)
    adapters = Counter(proposal.adapter_type.value for proposal in batch.proposals)
    confidences = Counter(proposal.confidence.value for proposal in batch.proposals)
    return DiscoveryAudit(
        seed_total=len(seed),
        proposal_total=len(batch.proposals),
        missing_company_ids=missing,
        extra_company_ids=extra,
        name_mismatches=name_mismatches,
        source_rank_mismatches=rank_mismatches,
        by_status=dict(sorted(statuses.items())),
        by_adapter=dict(sorted(adapters.items())),
        by_confidence=dict(sorted(confidences.items())),
    )


def proposal_to_disabled_source(proposal: SourceDiscoveryProposal) -> CompanySource:
    """Import a proposal as disabled configuration that still requires H2 review."""
    identity_strategy = (
        IdentityStrategy.EXTERNAL_ID
        if proposal.external_job_id_field is not None
        else IdentityStrategy.UNRESOLVED
    )
    return company_source_from_mapping(
        {
            "schema_version": 1,
            "company_id": proposal.company_id,
            "company_name": proposal.company_name,
            "status": "proposed"
            if proposal.status is not DiscoveryStatus.UNRESOLVED
            else "unresolved",
            "careers_url": proposal.official_careers_url,
            "adapter_type": proposal.adapter_type.value,
            "adapter_parameters": dict(proposal.adapter_parameters),
            "identity_strategy": identity_strategy.value,
            "date_strategy": {
                "field_name": proposal.publication_date_field,
                "basis": proposal.publication_date_basis.value,
                "verified_as_publication": proposal.publication_date_verified,
                "notes": "Imported from a provisional Phase 2 discovery proposal.",
            },
            "detail_strategy": proposal.detail_strategy.value,
            "enabled": False,
            "confidence": proposal.confidence.value,
            "evidence": [item.url for item in proposal.evidence],
            "low_confidence_approved": False,
            "exception_reason": proposal.access_concern,
            "notes": proposal.notes,
        }
    )


def _proposal_from_mapping(raw: Mapping[str, object]) -> SourceDiscoveryProposal:
    schema_version = _required_int(raw, "schema_version", "proposal")
    if schema_version != 1:
        raise ValueError(f"unsupported proposal schema_version: {schema_version}; supported=1")
    evidence_raw = raw.get("evidence")
    if not isinstance(evidence_raw, list):
        raise ValueError("proposal.evidence must be an array")
    evidence = tuple(
        _evidence_from_mapping(_as_mapping(item, f"proposal.evidence[{index}]"))
        for index, item in enumerate(evidence_raw)
    )
    parameters_raw = raw.get("adapter_parameters")
    if not isinstance(parameters_raw, Mapping):
        raise ValueError("proposal.adapter_parameters must be a table")
    parameters: dict[str, str] = {}
    for key, value in parameters_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("proposal.adapter_parameters keys must be non-empty strings")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"proposal.adapter_parameters.{key} must be a non-empty string")
        parameters[key] = value.strip()

    official_url = _nullable_url(raw.get("official_careers_url"), "official_careers_url")
    regional_url = _nullable_url(raw.get("regional_board_url"), "regional_board_url")
    list_endpoint = _nullable_url(raw.get("list_endpoint"), "list_endpoint")
    status = _enum_value(
        DiscoveryStatus,
        required_string(raw, "status", "proposal"),
        "proposal.status",
    )
    confidence = _enum_value(
        Confidence,
        required_string(raw, "confidence", "proposal"),
        "proposal.confidence",
    )
    if status is DiscoveryStatus.AUTO_VERIFIED:
        if official_url is None or not evidence:
            raise ValueError("auto-verified proposal requires an official URL and evidence")
        if confidence not in {Confidence.HIGH, Confidence.MEDIUM}:
            raise ValueError("auto-verified proposal requires high or medium confidence")
    if status is DiscoveryStatus.UNRESOLVED and confidence is not Confidence.UNKNOWN:
        raise ValueError("unresolved proposal must have unknown confidence")

    return SourceDiscoveryProposal(
        schema_version=schema_version,
        company_id=required_string(raw, "company_id", "proposal"),
        company_name=required_string(raw, "company_name", "proposal"),
        source_rank=_required_int(raw, "source_rank", "proposal"),
        priority=required_string(raw, "priority", "proposal"),
        status=status,
        official_careers_url=official_url,
        regional_board_url=regional_url,
        adapter_type=_enum_value(
            AdapterType,
            required_string(raw, "adapter_type", "proposal"),
            "proposal.adapter_type",
        ),
        adapter_parameters=parameters,
        listing_mode=_enum_value(
            ListingMode,
            required_string(raw, "listing_mode", "proposal"),
            "proposal.listing_mode",
        ),
        list_endpoint=list_endpoint,
        pagination=required_string(raw, "pagination", "proposal"),
        external_job_id_field=_nullable_string(
            raw.get("external_job_id_field"),
            "proposal.external_job_id_field",
        ),
        publication_date_field=_nullable_string(
            raw.get("publication_date_field"),
            "proposal.publication_date_field",
        ),
        publication_date_basis=_enum_value(
            DateBasis,
            required_string(raw, "publication_date_basis", "proposal"),
            "proposal.publication_date_basis",
        ),
        publication_date_verified=_required_bool(
            raw,
            "publication_date_verified",
            "proposal",
        ),
        title_field=_nullable_string(raw.get("title_field"), "proposal.title_field"),
        location_field=_nullable_string(raw.get("location_field"), "proposal.location_field"),
        detail_strategy=_enum_value(
            DetailStrategy,
            required_string(raw, "detail_strategy", "proposal"),
            "proposal.detail_strategy",
        ),
        confidence=confidence,
        evidence=evidence,
        access_concern=_nullable_string(raw.get("access_concern"), "proposal.access_concern"),
        notes=_optional_text(raw.get("notes"), "proposal.notes"),
    )


def _evidence_from_mapping(raw: Mapping[str, object]) -> DiscoveryEvidence:
    return DiscoveryEvidence(
        url=_required_url(raw, "url", "evidence"),
        evidence_type=required_string(raw, "evidence_type", "evidence"),
        note=required_string(raw, "note", "evidence"),
    )


def _as_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a table")
    return value


def _nullable_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be null or a non-empty string")
    return value.strip()


def _optional_text(value: object, path: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    return value.strip()


def _required_int(raw: Mapping[str, object], key: str, path: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be an integer")
    return value


def _required_bool(raw: Mapping[str, object], key: str, path: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be a boolean")
    return value


def _required_url(raw: Mapping[str, object], key: str, path: str) -> str:
    value = required_string(raw, key, path)
    _validate_url(value, f"{path}.{key}")
    return value


def _nullable_url(value: object, path: str) -> str | None:
    normalized = _nullable_string(value, path)
    if normalized is not None:
        _validate_url(normalized, path)
    return normalized


def _validate_url(value: str, path: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{path} must be an absolute HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{path} must not contain credentials")


def _enum_value[EnumType: StrEnum](
    enum_type: type[EnumType],
    value: str,
    path: str,
) -> EnumType:
    try:
        return enum_type(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{path} must be one of: {supported}") from error
