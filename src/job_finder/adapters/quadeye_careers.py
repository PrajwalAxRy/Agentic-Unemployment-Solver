"""Deterministic adapter for Quadeye's public Zoho Recruit proxy."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlencode, urlunsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpFailureCategory, HttpRequestError
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    DiagnosticSeverity,
)
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_text,
    normalize_title,
)

QUADEYE_ADAPTER_KEY = "quadeye_zoho_proxy"
QUADEYE_CAREERS_URL = "https://www.quadeye.com/jobs"
QUADEYE_JOBS_API = "https://www.quadeye.com/api/zoho-recruit/job-openings"
_ID_PATTERN = re.compile(r"[0-9]+")
_JOB_OPENING_PATTERN = re.compile(r"ZR_[0-9]+_JOB")


class QuadeyeCareersAdapter:
    """Retrieve Quadeye's complete public job collection in one request."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = QUADEYE_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                QUADEYE_JOBS_API,
                accepted_content_types=("application/json",),
                referer=QUADEYE_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url != QUADEYE_JOBS_API:
            return _failed(source, "unexpected_redirect", "Quadeye jobs API redirected.")
        try:
            root = _required_mapping(json.loads(response.body), "Quadeye response")
            if root.get("success") is not True:
                raise ValueError("Quadeye API did not report success=true.")
            raw_jobs = _required_list(root.get("data"), "Quadeye data")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            return _failed(source, "unsupported_schema", str(error))

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        for index, raw_job in enumerate(raw_jobs):
            try:
                job = _normalize_job(source, raw_job)
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_count=1,
                )
            external_id = job.external_job_id
            if external_id is None:
                raise AssertionError("Quadeye jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Quadeye returned a duplicate Zoho record ID.",
                        job_index=index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, diagnostics, page_count=1)
            seen_ids.add(external_id)
            jobs.append(job)

        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            diagnostics,
            page_count=1,
            complete=True,
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != QUADEYE_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Quadeye adapter requires adapter_key={QUADEYE_ADAPTER_KEY}."
        )
    if source.careers_url != QUADEYE_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Quadeye adapter requires careers_url={QUADEYE_CAREERS_URL}."
        )


def _normalize_job(source: CompanySource, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "Quadeye job")
    external_id = _required_string(raw, "id", "Quadeye job")
    if _ID_PATTERN.fullmatch(external_id) is None:
        raise ValueError("Quadeye job id must be numeric.")
    opening_id = _required_string(raw, "Job_Opening_ID", "Quadeye job")
    if _JOB_OPENING_PATTERN.fullmatch(opening_id) is None:
        raise ValueError("Quadeye Job_Opening_ID has an unsupported format.")
    if raw.get("Publish") is not True:
        raise ValueError("Quadeye API returned a non-public job.")
    opening_status = _required_string(raw, "Job_Opening_Status", "Quadeye job")
    title = _required_string(raw, "Posting_Title", "Quadeye job")
    opening_name = _required_string(raw, "Job_Opening_Name", "Quadeye job")
    if normalize_text(title) != normalize_text(opening_name):
        raise ValueError("Quadeye posting title did not match the opening name.")
    locations = _string_list(raw.get("Job_Location"), "Quadeye Job_Location")
    if not locations:
        raise ValueError("Quadeye Job_Location must not be empty.")
    description = _required_string(raw, "Job_Description", "Quadeye job")
    date_raw = _required_string(raw, "Date_Opened", "Quadeye job")
    try:
        opened_at = datetime.strptime(date_raw, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Quadeye Date_Opened must be an ISO date.") from error
    canonical_url = _job_url(external_id, title)
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=" | ".join(locations),
        location_normalized=_shared_locations(locations),
        published_at=opened_at,
        published_at_raw=date_raw,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": QUADEYE_ADAPTER_KEY,
            "job_opening_id": opening_id,
            "job_opening_status": opening_status,
            "job_type": _optional_string(raw.get("Job_Type")),
            "work_experience": _optional_string(raw.get("Work_Experience")),
            "date_opened": date_raw,
            "date_opened_basis": "unknown",
        },
    )


def _job_url(external_id: str, title: str) -> str:
    slug = _slug(title)
    return urlunsplit(
        (
            "https",
            "www.quadeye.com",
            f"/jobs/{external_id}/{slug}",
            urlencode({"source": "CareerSite"}),
            "",
        )
    )


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    if not slug:
        raise ValueError("Quadeye job title could not form a canonical slug.")
    return slug


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _required_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    return value


def _required_string(raw: Mapping[object, object], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} field {key} must be a non-empty string.")
    return re.sub(r"\s+", " ", value).strip()


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return re.sub(r"\s+", " ", value).strip()
    return None


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain only non-empty strings.")
        normalized = re.sub(r"\s+", " ", item).strip()
        if normalized not in result:
            result.append(normalized)
    return result


def _request_outcome(error: HttpRequestError) -> AdapterOutcome:
    return (
        AdapterOutcome.BLOCKED
        if error.category is HttpFailureCategory.ACCESS_BLOCK
        else AdapterOutcome.FAILED
    )


def _diagnostic(
    category: str,
    severity: DiagnosticSeverity,
    message: str,
    **context: object,
) -> AdapterDiagnostic:
    return AdapterDiagnostic(
        category=category,
        severity=severity,
        message=message,
        context={key: str(value) for key, value in context.items()},
    )


def _failed(source: CompanySource, category: str, message: str) -> AdapterResult:
    return _result(
        source,
        AdapterOutcome.FAILED,
        [],
        [_diagnostic(category, DiagnosticSeverity.ERROR, message)],
        page_count=1,
    )


def _result(
    source: CompanySource,
    outcome: AdapterOutcome,
    jobs: list[NormalizedJob],
    diagnostics: list[AdapterDiagnostic],
    *,
    page_count: int,
    complete: bool = False,
) -> AdapterResult:
    return AdapterResult(
        schema_version=1,
        source=source,
        outcome=outcome,
        jobs=tuple(jobs),
        page_count=page_count,
        complete=complete,
        diagnostics=tuple(diagnostics),
    )
