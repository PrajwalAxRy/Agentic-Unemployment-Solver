"""Company-source configuration and adapter result contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from job_finder.core.job_contracts import DateBasis, NormalizedJob

SUPPORTED_COMPANY_SOURCE_SCHEMA_VERSION = 1
SUPPORTED_ADAPTER_RESULT_SCHEMA_VERSION = 1


class SourceStatus(StrEnum):
    """Review and runtime state of a company source."""

    UNRESOLVED = "unresolved"
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    CUSTOM_ADAPTER_REQUIRED = "custom_adapter_required"


class AdapterType(StrEnum):
    """Adapter families recognized by the current schema."""

    UNRESOLVED = "unresolved"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    SMARTRECRUITERS = "smartrecruiters"
    EIGHTFOLD = "eightfold"
    ICIMS = "icims"
    ORACLE_CLOUD = "oracle_cloud"
    SUCCESSFACTORS = "successfactors"
    TALEO = "taleo"
    JOBVITE = "jobvite"
    DARWINBOX = "darwinbox"
    FRESHTEAM = "freshteam"
    GENERIC_STRUCTURED = "generic_structured"
    SEARCH_ONLY = "search_only"
    CUSTOM = "custom"
    UNSUPPORTED = "unsupported"


class IdentityStrategy(StrEnum):
    """Preferred stable identity available from a source."""

    UNRESOLVED = "unresolved"
    EXTERNAL_ID = "external_id"
    CANONICAL_URL = "canonical_url"
    FALLBACK_FINGERPRINT = "fallback_fingerprint"


class DetailStrategy(StrEnum):
    """How full job descriptions become available."""

    UNRESOLVED = "unresolved"
    LISTING_PAYLOAD = "listing_payload"
    DETAIL_ENDPOINT = "detail_endpoint"
    DETAIL_PAGE = "detail_page"
    UNAVAILABLE = "unavailable"


class Confidence(StrEnum):
    """Confidence in a reviewed source classification."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class DateStrategy:
    """Source field and interpretation used for publication evidence."""

    field_name: str | None
    basis: DateBasis
    verified_as_publication: bool
    notes: str


@dataclass(frozen=True, slots=True)
class CompanySource:
    """Validated source configuration for one canonical company."""

    schema_version: int
    company_id: str
    company_name: str
    status: SourceStatus
    careers_url: str | None
    adapter_type: AdapterType
    adapter_parameters: Mapping[str, str]
    identity_strategy: IdentityStrategy
    date_strategy: DateStrategy
    detail_strategy: DetailStrategy
    enabled: bool
    confidence: Confidence
    evidence: tuple[str, ...]
    low_confidence_approved: bool
    exception_reason: str | None
    notes: str


class AdapterOutcome(StrEnum):
    """Observable outcome of a bounded adapter listing attempt."""

    SUCCESS = "success"
    EMPTY = "empty"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    SUSPICIOUS = "suspicious"


class DiagnosticSeverity(StrEnum):
    """Severity of an adapter diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AdapterDiagnostic:
    """Sanitized evidence explaining adapter health or failure."""

    category: str
    severity: DiagnosticSeverity
    message: str
    context: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("diagnostic category must be non-empty")
        if not self.message.strip():
            raise ValueError("diagnostic message must be non-empty")


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Complete adapter output, including explicit non-success outcomes."""

    schema_version: int
    source: CompanySource
    outcome: AdapterOutcome
    jobs: tuple[NormalizedJob, ...]
    page_count: int
    complete: bool
    diagnostics: tuple[AdapterDiagnostic, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SUPPORTED_ADAPTER_RESULT_SCHEMA_VERSION:
            raise ValueError(
                "unsupported adapter result schema_version: "
                f"{self.schema_version}; supported={SUPPORTED_ADAPTER_RESULT_SCHEMA_VERSION}"
            )
        if self.page_count < 0:
            raise ValueError("adapter result page_count cannot be negative")
        if self.outcome is AdapterOutcome.SUCCESS and not self.jobs:
            raise ValueError("successful adapter result must contain jobs; use outcome='empty'")
        if self.outcome is AdapterOutcome.EMPTY and self.jobs:
            raise ValueError("empty adapter result cannot contain jobs")
        if self.outcome in {AdapterOutcome.SUCCESS, AdapterOutcome.EMPTY} and not self.complete:
            raise ValueError("successful or empty adapter result must be complete")
        if self.outcome in {
            AdapterOutcome.PARTIAL,
            AdapterOutcome.BLOCKED,
            AdapterOutcome.FAILED,
            AdapterOutcome.SUSPICIOUS,
        }:
            if self.complete:
                raise ValueError(f"{self.outcome.value} adapter result cannot be complete")
            if not self.diagnostics:
                raise ValueError(f"{self.outcome.value} adapter result requires diagnostics")
        for job in self.jobs:
            if job.company_id != self.source.company_id:
                raise ValueError("adapter job company_id does not match source company_id")
            if job.source_type != self.source.adapter_type.value:
                raise ValueError("adapter job source_type does not match source adapter_type")


_REQUIRED_ADAPTER_PARAMETERS: Mapping[AdapterType, tuple[str, ...]] = {
    AdapterType.GREENHOUSE: ("board_token",),
    AdapterType.LEVER: ("site",),
    AdapterType.ASHBY: ("board_name",),
    AdapterType.WORKDAY: ("host", "tenant", "site"),
    AdapterType.SMARTRECRUITERS: ("company_identifier",),
    AdapterType.EIGHTFOLD: ("tenant",),
    AdapterType.ICIMS: ("customer",),
    AdapterType.ORACLE_CLOUD: ("host", "site_number"),
    AdapterType.SUCCESSFACTORS: ("host", "category_path"),
    AdapterType.TALEO: ("organization",),
    AdapterType.JOBVITE: ("company",),
    AdapterType.DARWINBOX: ("tenant",),
    AdapterType.FRESHTEAM: ("account",),
    AdapterType.GENERIC_STRUCTURED: ("listing_url",),
    AdapterType.SEARCH_ONLY: ("search_url",),
    AdapterType.CUSTOM: ("adapter_key",),
}


def company_source_from_mapping(raw: Mapping[str, object]) -> CompanySource:
    """Validate a company source from parsed registry content."""
    schema_version = _required_int(raw, "schema_version")
    if schema_version != SUPPORTED_COMPANY_SOURCE_SCHEMA_VERSION:
        raise ValueError(
            "unsupported company source schema_version: "
            f"{schema_version}; supported={SUPPORTED_COMPANY_SOURCE_SCHEMA_VERSION}"
        )

    company_id = _required_string(raw, "company_id")
    company_name = _required_string(raw, "company_name")
    status = _enum_value(SourceStatus, _required_string(raw, "status"), "status")
    adapter_type = _enum_value(
        AdapterType,
        _required_string(raw, "adapter_type"),
        "adapter_type",
    )
    identity_strategy = _enum_value(
        IdentityStrategy,
        _required_string(raw, "identity_strategy"),
        "identity_strategy",
    )
    detail_strategy = _enum_value(
        DetailStrategy,
        _required_string(raw, "detail_strategy"),
        "detail_strategy",
    )
    confidence = _enum_value(
        Confidence,
        _required_string(raw, "confidence"),
        "confidence",
    )

    careers_url = _optional_string(raw.get("careers_url"), "careers_url")
    if careers_url is not None:
        _validate_public_url(careers_url, "careers_url")

    parameters_raw = raw.get("adapter_parameters")
    if not isinstance(parameters_raw, Mapping):
        raise ValueError("adapter_parameters must be a table")
    adapter_parameters: dict[str, str] = {}
    for key, value in parameters_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("adapter_parameters keys must be non-empty strings")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"adapter_parameters.{key} must be a non-empty string")
        adapter_parameters[key] = value.strip()

    missing_parameters = [
        name
        for name in _REQUIRED_ADAPTER_PARAMETERS.get(adapter_type, ())
        if name not in adapter_parameters
    ]
    if missing_parameters:
        raise ValueError(
            f"adapter_type={adapter_type.value} requires parameters: "
            + ", ".join(missing_parameters)
        )

    date_raw = raw.get("date_strategy")
    if not isinstance(date_raw, Mapping):
        raise ValueError("date_strategy must be a table")
    verified = date_raw.get("verified_as_publication")
    if not isinstance(verified, bool):
        raise ValueError("date_strategy.verified_as_publication must be a boolean")
    date_strategy = DateStrategy(
        field_name=_optional_string(date_raw.get("field_name"), "date_strategy.field_name"),
        basis=_enum_value(
            DateBasis,
            _required_string(date_raw, "basis"),
            "date_strategy.basis",
        ),
        verified_as_publication=verified,
        notes=_optional_text(date_raw.get("notes"), "date_strategy.notes"),
    )

    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    low_confidence_approved = raw.get("low_confidence_approved")
    if not isinstance(low_confidence_approved, bool):
        raise ValueError("low_confidence_approved must be a boolean")
    evidence = _string_tuple(raw.get("evidence"), "evidence", allow_empty=True)
    exception_reason = _optional_string(raw.get("exception_reason"), "exception_reason")
    notes = _optional_text(raw.get("notes"), "notes")

    if enabled:
        if status is not SourceStatus.ENABLED:
            raise ValueError("enabled source must have status='enabled'")
        if careers_url is None:
            raise ValueError("enabled source requires careers_url")
        if adapter_type in {AdapterType.UNRESOLVED, AdapterType.UNSUPPORTED}:
            raise ValueError("enabled source requires a supported adapter_type")
        if confidence is Confidence.LOW and not low_confidence_approved:
            raise ValueError("enabled low-confidence source requires explicit approval")
        if not evidence:
            raise ValueError("enabled source requires evidence")

    if status in {SourceStatus.BLOCKED, SourceStatus.UNSUPPORTED} and exception_reason is None:
        raise ValueError(f"status={status.value} requires exception_reason")

    return CompanySource(
        schema_version=schema_version,
        company_id=company_id,
        company_name=company_name,
        status=status,
        careers_url=careers_url,
        adapter_type=adapter_type,
        adapter_parameters=adapter_parameters,
        identity_strategy=identity_strategy,
        date_strategy=date_strategy,
        detail_strategy=detail_strategy,
        enabled=enabled,
        confidence=confidence,
        evidence=evidence,
        low_confidence_approved=low_confidence_approved,
        exception_reason=exception_reason,
        notes=notes,
    )


def _validate_public_url(value: str, path: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{path} must be an absolute HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{path} must not contain credentials")


def _required_string(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, path: str) -> str | None:
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


def _required_int(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _string_tuple(value: object, path: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a non-empty array"
        raise ValueError(f"{path} must be {qualifier} of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path} must contain only non-empty strings")
    return tuple(item.strip() for item in value if isinstance(item, str))


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
