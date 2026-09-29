"""Adapter for Darwinbox public candidate-career APIs."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

from job_finder.adapters.base import request_failure_diagnostic, require_source_configuration
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpRequestError,
)
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
    normalize_title,
)

DEFAULT_PAGE_SIZE = 10
DEFAULT_MAX_PAGES = 500
_TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$", re.IGNORECASE)


class DarwinboxAdapter:
    """Retrieve complete Darwinbox listings and optional public job details."""

    adapter_type = AdapterType.DARWINBOX

    def __init__(
        self,
        client: BoundedHttpClient | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self._client = client or BoundedHttpClient()
        self._page_size = page_size
        self._max_pages = max_pages

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        tenant = _tenant(source)
        referer = _careers_url(tenant)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()
        expected_total: int | None = None
        raw_job_count = 0
        parse_error_count = 0
        uncertain_date_count = 0
        missing_date_count = 0
        missing_location_count = 0
        page_count = 0

        for page_number in range(1, self._max_pages + 1):
            endpoint = _api_base(tenant) + f"/job?page={page_number}"
            try:
                response = self._client.get(
                    endpoint,
                    accepted_content_types=("application/json",),
                    referer=referer,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                if jobs:
                    return _result(
                        source,
                        AdapterOutcome.PARTIAL,
                        jobs,
                        page_count,
                        diagnostics,
                    )
                outcome = (
                    AdapterOutcome.BLOCKED
                    if error.category is HttpFailureCategory.ACCESS_BLOCK
                    else AdapterOutcome.FAILED
                )
                return _result(source, outcome, jobs, page_count, diagnostics)

            page_count += 1
            try:
                payload: Any = json.loads(response.body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                diagnostics.append(
                    _diagnostic(
                        "invalid_json",
                        DiagnosticSeverity.ERROR,
                        "Darwinbox response was not valid JSON.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_count,
                    diagnostics,
                )
            try:
                raw_jobs, total = _listing_collection(payload)
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "unsupported_schema",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_count,
                    diagnostics,
                )
            if len(raw_jobs) > self._page_size:
                diagnostics.append(
                    _diagnostic(
                        "page_size_exceeded",
                        DiagnosticSeverity.ERROR,
                        "Darwinbox returned more jobs than its configured page size.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    page_count,
                    diagnostics,
                )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                diagnostics.append(
                    _diagnostic(
                        "inconsistent_total",
                        DiagnosticSeverity.ERROR,
                        "Darwinbox jobscount changed during non-empty pagination.",
                        page_number=page_number,
                        expected=expected_total,
                        observed=total,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    page_count,
                    diagnostics,
                )

            fingerprint = hashlib.sha256(response.body).hexdigest()
            if raw_jobs and fingerprint in seen_pages:
                diagnostics.append(
                    _diagnostic(
                        "repeated_page",
                        DiagnosticSeverity.ERROR,
                        "Darwinbox returned a repeated non-empty page.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    page_count,
                    diagnostics,
                )
            seen_pages.add(fingerprint)
            if raw_job_count + len(raw_jobs) > expected_total:
                diagnostics.append(
                    _diagnostic(
                        "collection_exceeds_total",
                        DiagnosticSeverity.ERROR,
                        "Darwinbox returned more jobs than its first-page total.",
                        page_number=page_number,
                        expected=expected_total,
                        observed=raw_job_count + len(raw_jobs),
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    page_count,
                    diagnostics,
                )
            if not raw_jobs and raw_job_count < expected_total:
                diagnostics.append(
                    _diagnostic(
                        "premature_empty_page",
                        DiagnosticSeverity.ERROR,
                        "Darwinbox returned an empty page before the reported total.",
                        page_number=page_number,
                        expected=expected_total,
                        observed=raw_job_count,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    page_count,
                    diagnostics,
                )

            for job_index, raw_job in enumerate(raw_jobs):
                try:
                    job = _normalize_listing(source, tenant, raw_job)
                except ValueError as error:
                    parse_error_count += 1
                    diagnostics.append(
                        _diagnostic(
                            "malformed_job",
                            DiagnosticSeverity.ERROR,
                            str(error),
                            page_number=page_number,
                            job_index=job_index,
                        )
                    )
                    continue
                if job.external_job_id in seen_ids:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "Darwinbox pagination returned a duplicate job ID.",
                            page_number=page_number,
                            job_index=job_index,
                        )
                    )
                    return _result(
                        source,
                        AdapterOutcome.SUSPICIOUS,
                        jobs,
                        page_count,
                        diagnostics,
                    )
                if job.external_job_id is not None:
                    seen_ids.add(job.external_job_id)
                if job.published_at_raw is None:
                    missing_date_count += 1
                else:
                    uncertain_date_count += 1
                if job.source_metadata.get("listing_location_missing") is True:
                    missing_location_count += 1
                jobs.append(job)

            raw_job_count += len(raw_jobs)
            if raw_job_count >= expected_total:
                break
        else:
            diagnostics.append(
                _diagnostic(
                    "pagination_limit",
                    DiagnosticSeverity.ERROR,
                    "Darwinbox pagination exceeded the configured page limit.",
                    expected=expected_total or 0,
                    observed=raw_job_count,
                )
            )
            return _result(
                source,
                AdapterOutcome.SUSPICIOUS,
                jobs,
                page_count,
                diagnostics,
            )

        if uncertain_date_count:
            diagnostics.append(
                _diagnostic(
                    "unverified_job_posting_on",
                    DiagnosticSeverity.WARNING,
                    "Darwinbox job_posting_on is retained as uncertain date evidence.",
                    count=uncertain_date_count,
                )
            )
        if missing_date_count:
            diagnostics.append(
                _diagnostic(
                    "missing_publication_date",
                    DiagnosticSeverity.WARNING,
                    "Darwinbox listings without job_posting_on remain explicit.",
                    count=missing_date_count,
                )
            )
        if missing_location_count:
            diagnostics.append(
                _diagnostic(
                    "missing_location",
                    DiagnosticSeverity.WARNING,
                    "Darwinbox listings without locations require detail review.",
                    count=missing_location_count,
                )
            )
        if parse_error_count:
            return _result(
                source,
                AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                jobs,
                page_count,
                diagnostics,
            )
        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            page_count,
            diagnostics,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one Darwinbox detail payload without changing listing identity."""
        tenant = _tenant(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Darwinbox detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("Darwinbox detail retrieval requires an external job ID.")
        response = self._client.get(
            _api_base(tenant) + "/job/" + quote(job.external_job_id, safe=""),
            accepted_content_types=("application/json",),
            referer=_careers_url(tenant),
        )
        try:
            payload: Any = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Darwinbox detail response was not valid JSON.") from error
        raw_job = _detail_job(payload)
        detail_id = _required_string(raw_job, "id")
        if detail_id != job.external_job_id:
            raise ValueError("Darwinbox detail response job ID does not match the listing.")
        title = _required_string(raw_job, "title")
        locations = _locations(raw_job)
        if _is_remote(raw_job.get("is_remote")):
            locations.append("Remote")
        if not locations:
            locations = [job.location_original]
        raw_description = _optional_string(raw_job.get("jd"))
        description = _plain_text(raw_description) if raw_description is not None else None
        if not description:
            description = None
        published_at_raw = _raw_date(raw_job.get("job_posting_on")) or job.published_at_raw
        published_at = _parse_epoch(raw_job.get("job_posting_on")) or job.published_at
        source_metadata = dict(job.source_metadata)
        source_metadata.update(
            {
                "created_on_raw": _optional_string(raw_job.get("created_on")),
                "detail_location_missing": not _locations(raw_job),
                "experience_from": raw_job.get("experience_from_num"),
                "experience_to": raw_job.get("experience_to_num"),
                "is_remote": raw_job.get("is_remote"),
                "timezone": raw_job.get("timezone"),
            }
        )
        return NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=self.adapter_type.value,
            external_job_id=detail_id,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=" | ".join(_unique_strings(locations)),
            location_normalized=_shared_locations(locations),
            published_at=published_at,
            published_at_raw=published_at_raw,
            date_basis=DateBasis.UNKNOWN,
            canonical_url=_job_url(tenant, detail_id),
            description=description,
            description_hash=(
                hashlib.sha256(description.encode("utf-8")).hexdigest()
                if description is not None
                else None
            ),
            source_metadata=source_metadata,
        )


def _tenant(source: CompanySource) -> str:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.DARWINBOX,
        required_parameters=("tenant",),
    )
    tenant = parameters["tenant"].strip().lower()
    if not _TENANT_PATTERN.fullmatch(tenant):
        raise ValueError("Darwinbox tenant must contain only letters, digits, and hyphens.")
    return tenant


def _api_base(tenant: str) -> str:
    return f"https://{tenant}.darwinbox.in/ms/candidateapi"


def _careers_url(tenant: str) -> str:
    return f"https://{tenant}.darwinbox.in/ms/candidate/careers"


def _job_url(tenant: str, job_id: str) -> str:
    return _careers_url(tenant) + "/" + quote(job_id, safe="")


def _listing_collection(payload: object) -> tuple[list[object], int]:
    if not isinstance(payload, Mapping):
        raise ValueError("Darwinbox response root must be an object.")
    message = payload.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Darwinbox response requires a message object.")
    jobs = message.get("jobs")
    total = message.get("jobscount")
    if not isinstance(jobs, list):
        raise ValueError("Darwinbox message requires a jobs array.")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError("Darwinbox jobscount must be a non-negative integer.")
    return jobs, total


def _detail_job(payload: object) -> Mapping[object, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("Darwinbox detail response root must be an object.")
    message = payload.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Darwinbox detail response requires a message object.")
    jobs = message.get("job")
    if not isinstance(jobs, list) or len(jobs) != 1 or not isinstance(jobs[0], Mapping):
        raise ValueError("Darwinbox detail response requires exactly one job object.")
    return jobs[0]


def _normalize_listing(
    source: CompanySource,
    tenant: str,
    raw_job: object,
) -> NormalizedJob:
    if not isinstance(raw_job, Mapping):
        raise ValueError("Darwinbox job must be an object.")
    external_id = _required_string(raw_job, "id")
    title = _required_string(raw_job, "title")
    locations = _locations(raw_job)
    location_missing = not locations
    if location_missing:
        locations = ["Location unavailable"]
    date_value = raw_job.get("job_posting_on")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.DARWINBOX.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=" | ".join(_unique_strings(locations)),
        location_normalized=_shared_locations(locations),
        published_at=_parse_epoch(date_value),
        published_at_raw=_raw_date(date_value),
        date_basis=DateBasis.UNKNOWN,
        canonical_url=_job_url(tenant, external_id),
        source_metadata={
            "created_on_raw": _optional_string(raw_job.get("created_on")),
            "experience_from": raw_job.get("experience_from_num"),
            "experience_to": raw_job.get("experience_to_num"),
            "listing_location_missing": location_missing,
            "timezone": raw_job.get("timezone"),
        },
    )


def _locations(raw_job: Mapping[object, object]) -> list[str]:
    for key in ("officelocation_show_arr", "tool_tip_locations"):
        value = raw_job.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list) and all(
            isinstance(item, str) and item.strip() for item in value
        ):
            return [item.strip() for item in value if isinstance(item, str)]
    return []


def _raw_date(value: object) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_epoch(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    seconds = value / 1000 if value > 100_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _is_remote(value: object) -> bool:
    return (
        value is True
        or value == 1
        or (isinstance(value, str) and value.strip().casefold() in {"1", "true", "yes"})
    )


def _result(
    source: CompanySource,
    outcome: AdapterOutcome,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    *,
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


def _required_string(raw: Mapping[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Darwinbox job field {key} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        key = value.casefold()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return result


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _plain_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html.unescape(value))
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
