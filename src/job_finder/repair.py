"""Sanitized, inactive source-repair requests and proposal validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from job_finder.core.company_registry import CompanySourceRegistry

REPAIR_SCHEMA_VERSION = 1
_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "access_token",
    "session_token",
)


class RepairChangeType(StrEnum):
    """Supported high-level dispositions for a source repair."""

    COMPANY_PARAMETER = "company_parameter"
    SOURCE_URL = "source_url"
    FIELD_MAPPING = "field_mapping"
    ADAPTER_REPAIR = "adapter_repair"
    CUSTOM_ADAPTER = "custom_adapter"
    MARK_UNSUPPORTED = "mark_unsupported"


class RepairConfidence(StrEnum):
    """LLM confidence retained for human review, never automatic activation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class RepairEvidence:
    """Body-free verification evidence for one unhealthy company source."""

    verification_generated_at: str
    outcome: str
    complete: bool
    job_count: int
    page_count: int
    missing_field_count: int
    attempt_count: int
    exception_categories: tuple[str, ...]
    failure_categories: tuple[str, ...]
    anomaly_categories: tuple[str, ...]
    sample_job_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepairRequest:
    """Strict LLM input that carries evidence but grants no write authority."""

    schema_version: int
    proposal_id: str
    registry_version: str
    company_id: str
    company_name: str
    careers_url: str
    adapter_type: str
    adapter_parameters: Mapping[str, str]
    identity_strategy: str
    date_strategy: Mapping[str, object]
    detail_strategy: str
    evidence: RepairEvidence
    constraints: tuple[str, ...]
    required_output_fields: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProposedChange:
    """One exact inactive path-level change proposed for human review."""

    path: str
    before: str | None
    after: str | None


@dataclass(frozen=True, slots=True)
class RepairProposal:
    """Validated LLM proposal that cannot activate itself."""

    schema_version: int
    proposal_id: str
    company_id: str
    proposer_model: str
    summary: str
    change_type: RepairChangeType
    confidence: RepairConfidence
    rationale: str
    changes: tuple[ProposedChange, ...]
    fixture_test_plan: tuple[str, ...]
    live_test_plan: tuple[str, ...]
    rollback_plan: tuple[str, ...]
    activation_status: str

    def as_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["change_type"] = self.change_type.value
        payload["confidence"] = self.confidence.value
        return payload


def build_repair_request(
    registry: CompanySourceRegistry,
    verification_path: Path,
    *,
    company_id: str,
) -> RepairRequest:
    """Build a deterministic request from one unhealthy sanitized verification record."""
    verification = _load_json_object(verification_path, "verification report")
    if _required_int(verification, "schema_version") != 2:
        raise ValueError("repair requests require verification report schema_version 2")
    report_registry = _required_string(verification, "registry_version")
    if report_registry != registry.registry_version:
        raise ValueError(
            "verification registry_version does not match active registry: "
            f"{report_registry} != {registry.registry_version}"
        )
    generated_at = _required_string(verification, "generated_at")
    record = _verification_record(verification, company_id)
    outcome = _required_string(record, "outcome")
    if outcome in {"success", "empty"}:
        raise ValueError("repair requests require an unhealthy or suspicious source record")

    entry = next(
        (item for item in registry.entries if item.source.company_id == company_id),
        None,
    )
    if entry is None:
        raise ValueError(f"company_id is not present in active registry: {company_id}")
    source = entry.source
    record_adapter = _required_string(record, "adapter_type")
    if record_adapter != source.adapter_type.value:
        raise ValueError("verification adapter_type does not match active registry")
    parameters = _safe_string_mapping(source.adapter_parameters, "adapter_parameters")
    evidence = RepairEvidence(
        verification_generated_at=generated_at,
        outcome=outcome,
        complete=_required_bool(record, "complete"),
        job_count=_non_negative_int(record, "job_count"),
        page_count=_non_negative_int(record, "page_count"),
        missing_field_count=_non_negative_int(record, "missing_field_count"),
        attempt_count=_non_negative_int(record, "attempt_count"),
        exception_categories=_string_tuple(record, "exception_categories"),
        failure_categories=_string_tuple(record, "failure_categories"),
        anomaly_categories=_string_tuple(record, "anomaly_categories"),
        sample_job_urls=_public_url_tuple(record, "sample_job_urls"),
    )
    proposal_id = _proposal_id(
        registry.registry_version,
        company_id,
        evidence,
    )
    request = RepairRequest(
        schema_version=REPAIR_SCHEMA_VERSION,
        proposal_id=proposal_id,
        registry_version=registry.registry_version,
        company_id=source.company_id,
        company_name=source.company_name,
        careers_url=source.careers_url or "",
        adapter_type=source.adapter_type.value,
        adapter_parameters=parameters,
        identity_strategy=source.identity_strategy.value,
        date_strategy={
            "field_name": source.date_strategy.field_name,
            "basis": source.date_strategy.basis.value,
            "verified_as_publication": source.date_strategy.verified_as_publication,
            "notes": source.date_strategy.notes,
        },
        detail_strategy=source.detail_strategy.value,
        evidence=evidence,
        constraints=(
            "Use only public job sources and the supplied sanitized evidence.",
            "Do not propose authentication, CAPTCHA bypass, session reuse, or rate-limit bypass.",
            "Do not edit active configuration or code; return an inactive proposal only.",
            "Preserve the last working configuration and include exact rollback steps.",
            "Require fixture tests and a bounded live verification before activation.",
            "Human approval under checkpoint H11 is required before activation.",
        ),
        required_output_fields=(
            "schema_version",
            "proposal_id",
            "company_id",
            "proposer_model",
            "summary",
            "change_type",
            "confidence",
            "rationale",
            "changes",
            "fixture_test_plan",
            "live_test_plan",
            "rollback_plan",
            "activation_status",
        ),
    )
    _require_public_url(request.careers_url, "careers_url")
    return request


def load_repair_request(path: Path) -> RepairRequest:
    """Load a previously generated request without trusting arbitrary extra content."""
    raw = _load_json_object(path, "repair request")
    if _required_int(raw, "schema_version") != REPAIR_SCHEMA_VERSION:
        raise ValueError("unsupported repair request schema_version")
    evidence_raw = _required_mapping(raw, "evidence")
    evidence = RepairEvidence(
        verification_generated_at=_required_string(evidence_raw, "verification_generated_at"),
        outcome=_required_string(evidence_raw, "outcome"),
        complete=_required_bool(evidence_raw, "complete"),
        job_count=_non_negative_int(evidence_raw, "job_count"),
        page_count=_non_negative_int(evidence_raw, "page_count"),
        missing_field_count=_non_negative_int(evidence_raw, "missing_field_count"),
        attempt_count=_non_negative_int(evidence_raw, "attempt_count"),
        exception_categories=_string_tuple(evidence_raw, "exception_categories"),
        failure_categories=_string_tuple(evidence_raw, "failure_categories"),
        anomaly_categories=_string_tuple(evidence_raw, "anomaly_categories"),
        sample_job_urls=_public_url_tuple(evidence_raw, "sample_job_urls"),
    )
    request = RepairRequest(
        schema_version=REPAIR_SCHEMA_VERSION,
        proposal_id=_required_string(raw, "proposal_id"),
        registry_version=_required_string(raw, "registry_version"),
        company_id=_required_string(raw, "company_id"),
        company_name=_required_string(raw, "company_name"),
        careers_url=_required_string(raw, "careers_url"),
        adapter_type=_required_string(raw, "adapter_type"),
        adapter_parameters=_safe_string_mapping(
            _required_mapping(raw, "adapter_parameters"),
            "adapter_parameters",
        ),
        identity_strategy=_required_string(raw, "identity_strategy"),
        date_strategy=dict(_required_mapping(raw, "date_strategy")),
        detail_strategy=_required_string(raw, "detail_strategy"),
        evidence=evidence,
        constraints=_string_tuple(raw, "constraints", allow_empty=False),
        required_output_fields=_string_tuple(raw, "required_output_fields", allow_empty=False),
    )
    _require_public_url(request.careers_url, "careers_url")
    if request.proposal_id != _proposal_id(
        request.registry_version,
        request.company_id,
        request.evidence,
    ):
        raise ValueError("repair request proposal_id does not match its evidence")
    return request


def validate_repair_proposal(
    request: RepairRequest,
    raw: Mapping[str, object],
) -> RepairProposal:
    """Validate strict LLM output while forcing the proposal to remain inactive."""
    if _required_int(raw, "schema_version") != REPAIR_SCHEMA_VERSION:
        raise ValueError("unsupported repair proposal schema_version")
    proposal_id = _required_string(raw, "proposal_id")
    company_id = _required_string(raw, "company_id")
    if proposal_id != request.proposal_id:
        raise ValueError("repair proposal_id does not match the request")
    if company_id != request.company_id:
        raise ValueError("repair company_id does not match the request")
    activation_status = _required_string(raw, "activation_status")
    if activation_status != "inactive":
        raise ValueError("repair proposals must remain inactive until checkpoint H11 approval")

    changes_raw = raw.get("changes")
    if not isinstance(changes_raw, list) or not changes_raw:
        raise ValueError("changes must be a non-empty array")
    changes: list[ProposedChange] = []
    for index, item in enumerate(changes_raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"changes[{index}] must be an object")
        path = _required_string(item, "path")
        before = _optional_string(item.get("before"), f"changes[{index}].before")
        after = _optional_string(item.get("after"), f"changes[{index}].after")
        _reject_sensitive(path, f"changes[{index}].path")
        if before is not None:
            _reject_sensitive(before, f"changes[{index}].before")
        if after is not None:
            _reject_sensitive(after, f"changes[{index}].after")
        if before == after:
            raise ValueError(f"changes[{index}] must change the value")
        changes.append(ProposedChange(path=path, before=before, after=after))

    return RepairProposal(
        schema_version=REPAIR_SCHEMA_VERSION,
        proposal_id=proposal_id,
        company_id=company_id,
        proposer_model=_safe_string(raw, "proposer_model"),
        summary=_safe_string(raw, "summary"),
        change_type=_enum_value(RepairChangeType, raw, "change_type"),
        confidence=_enum_value(RepairConfidence, raw, "confidence"),
        rationale=_safe_string(raw, "rationale"),
        changes=tuple(changes),
        fixture_test_plan=_safe_string_tuple(raw, "fixture_test_plan"),
        live_test_plan=_safe_string_tuple(raw, "live_test_plan"),
        rollback_plan=_safe_string_tuple(raw, "rollback_plan"),
        activation_status=activation_status,
    )


def load_and_validate_repair_proposal(
    request: RepairRequest,
    proposal_path: Path,
) -> RepairProposal:
    return validate_repair_proposal(
        request,
        _load_json_object(proposal_path, "repair proposal"),
    )


def preview_registry_with_proposal(
    registry: CompanySourceRegistry,
    request: RepairRequest,
    proposal: RepairProposal,
) -> CompanySourceRegistry:
    """Apply reviewed configuration fields in memory for bounded tests only."""
    if proposal.activation_status != "inactive":
        raise ValueError("only inactive proposals may be previewed")
    if proposal.proposal_id != request.proposal_id or proposal.company_id != request.company_id:
        raise ValueError("repair proposal does not match the request")
    if registry.registry_version != request.registry_version:
        raise ValueError("active registry version does not match the repair request")
    entry_index = next(
        (
            index
            for index, item in enumerate(registry.entries)
            if item.source.company_id == request.company_id
        ),
        None,
    )
    if entry_index is None:
        raise ValueError(f"company_id is not present in active registry: {request.company_id}")

    entry = registry.entries[entry_index]
    source = entry.source
    parameters = dict(source.adapter_parameters)
    careers_url = source.careers_url
    seen_paths: set[str] = set()
    prefix = f"sources[{request.company_id}]."
    for change in proposal.changes:
        if change.path in seen_paths:
            raise ValueError(f"repair proposal repeats change path: {change.path}")
        seen_paths.add(change.path)
        if not change.path.startswith(prefix):
            raise ValueError("repair change path targets a different company")
        suffix = change.path[len(prefix) :]
        if suffix == "careers_url":
            if careers_url != change.before or change.after is None:
                raise ValueError("careers_url change does not match the active registry")
            _require_public_url(change.after, "proposed careers_url")
            careers_url = change.after
            continue
        parameter_prefix = "adapter_parameters."
        if suffix.startswith(parameter_prefix):
            key = suffix[len(parameter_prefix) :]
            if not key or "." in key:
                raise ValueError("adapter parameter change path is invalid")
            if parameters.get(key) != change.before or change.after is None:
                raise ValueError(f"adapter parameter change does not match active value: {key}")
            _reject_sensitive(key, "proposed adapter parameter")
            _reject_sensitive(change.after, f"proposed adapter parameter {key}")
            parameters[key] = change.after
            continue
        raise ValueError(
            "inactive preview supports only careers_url and adapter_parameters changes"
        )

    preview_source = replace(
        source,
        careers_url=careers_url,
        adapter_parameters=parameters,
    )
    preview_entries = list(registry.entries)
    preview_entries[entry_index] = replace(entry, source=preview_source)
    return replace(
        registry,
        registry_version=f"{registry.registry_version}+{proposal.proposal_id}-preview",
        entries=tuple(preview_entries),
    )


def write_repair_artifact(value: RepairRequest | RepairProposal, path: Path) -> None:
    """Write an ignored request or inactive proposal using deterministic JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value.as_json(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _proposal_id(
    registry_version: str,
    company_id: str,
    evidence: RepairEvidence,
) -> str:
    payload = json.dumps(
        {
            "registry_version": registry_version,
            "company_id": company_id,
            "evidence": asdict(evidence),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "repair-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _verification_record(
    report: Mapping[str, object],
    company_id: str,
) -> Mapping[str, object]:
    records = report.get("records")
    if not isinstance(records, list):
        raise ValueError("verification report records must be an array")
    matches = [
        item
        for item in records
        if isinstance(item, Mapping) and item.get("company_id") == company_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"verification report must contain exactly one record for company_id={company_id}"
        )
    return matches[0]


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {label}: {path}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a JSON object")
    return raw


def _required_mapping(raw: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _required_string(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _safe_string(raw: Mapping[str, object], key: str) -> str:
    value = _required_string(raw, key)
    _reject_sensitive(value, key)
    return value


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string or null")
    return value.strip()


def _required_bool(raw: Mapping[str, object], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _required_int(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _non_negative_int(raw: Mapping[str, object], key: str) -> int:
    value = _required_int(raw, key)
    if value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def _string_tuple(
    raw: Mapping[str, object],
    key: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a non-empty array"
        raise ValueError(f"{key} must be {qualifier} of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{key} must contain only non-empty strings")
    return tuple(item.strip() for item in value if isinstance(item, str))


def _safe_string_tuple(raw: Mapping[str, object], key: str) -> tuple[str, ...]:
    values = _string_tuple(raw, key, allow_empty=False)
    for index, value in enumerate(values):
        _reject_sensitive(value, f"{key}[{index}]")
    return values


def _public_url_tuple(raw: Mapping[str, object], key: str) -> tuple[str, ...]:
    values = _string_tuple(raw, key)
    for index, value in enumerate(values):
        _require_public_url(value, f"{key}[{index}]")
    return values


def _require_public_url(value: str, path: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{path} must be a public HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{path} must not contain credentials")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        _reject_sensitive(key, f"{path} query parameter")


def _safe_string_mapping(value: Mapping[str, object], path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{path} keys must be non-empty strings")
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{path}.{key} must be a non-empty string")
        _reject_sensitive(key, f"{path}.{key}")
        _reject_sensitive(item, f"{path}.{key}")
        result[key.strip()] = item.strip()
    return result


def _reject_sensitive(value: str, path: str) -> None:
    lowered = value.casefold()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        raise ValueError(f"{path} contains a sensitive-data marker")


def _enum_value[EnumType: StrEnum](
    enum_type: type[EnumType],
    raw: Mapping[str, object],
    key: str,
) -> EnumType:
    value = _required_string(raw, key)
    try:
        return enum_type(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{key} must be one of: {supported}") from error
