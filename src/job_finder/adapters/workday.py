"""Adapter for Workday's public Candidate Experience APIs."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlsplit

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

DEFAULT_PAGE_SIZE = 20
DEFAULT_MAX_PAGES = 500


class WorkdayAdapter:
    """Retrieve complete public Workday listings and optional job details."""

    adapter_type = AdapterType.WORKDAY

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
        parameters = _workday_parameters(source)
        endpoint = _api_base(parameters) + "/jobs"
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_keys: set[str] = set()
        seen_pages: set[str] = set()
        expected_total: int | None = None
        raw_job_count = 0
        parse_error_count = 0
        missing_location_count = 0
        relative_date_count = 0
        missing_date_count = 0
        page_count = 0

        for page_index in range(self._max_pages):
            offset = raw_job_count
            try:
                response = self._client.post_json(
                    endpoint,
                    {
                        "appliedFacets": {},
                        "limit": self._page_size,
                        "offset": offset,
                        "searchText": "",
                    },
                    accepted_content_types=("application/json",),
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
                        "Workday response was not valid JSON.",
                        page_index=page_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_count,
                    diagnostics,
                )
            if not isinstance(payload, Mapping):
                return _schema_failure(
                    source,
                    jobs,
                    page_count,
                    diagnostics,
                    "Workday response root must be an object.",
                    page_index,
                )
            raw_jobs = payload.get("jobPostings")
            total = payload.get("total")
            if not isinstance(raw_jobs, list):
                return _schema_failure(
                    source,
                    jobs,
                    page_count,
                    diagnostics,
                    "Workday response requires a jobPostings array.",
                    page_index,
                )
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                return _schema_failure(
                    source,
                    jobs,
                    page_count,
                    diagnostics,
                    "Workday total must be a non-negative integer.",
                    page_index,
                )
            if len(raw_jobs) > self._page_size:
                diagnostics.append(
                    _diagnostic(
                        "page_size_exceeded",
                        DiagnosticSeverity.ERROR,
                        "Workday returned more jobs than the requested page limit.",
                        page_index=page_index,
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
            elif total not in {0, expected_total}:
                diagnostics.append(
                    _diagnostic(
                        "inconsistent_total",
                        DiagnosticSeverity.ERROR,
                        "Workday total changed during pagination; completeness is unknown.",
                        page_index=page_index,
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
                        "Workday returned a repeated non-empty page; completeness is unknown.",
                        page_index=page_index,
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
                        "Workday returned more jobs than the first-page total.",
                        page_index=page_index,
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
                        "Workday returned an empty page before the reported total was reached.",
                        page_index=page_index,
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
                    job = _normalize_listing(source, parameters, raw_job)
                except ValueError as error:
                    parse_error_count += 1
                    diagnostics.append(
                        _diagnostic(
                            "malformed_job",
                            DiagnosticSeverity.ERROR,
                            str(error),
                            page_index=page_index,
                            job_index=job_index,
                        )
                    )
                    continue
                identity = job.external_job_id or job.canonical_url
                if identity in seen_keys:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "Workday pagination returned a duplicate job identity.",
                            page_index=page_index,
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
                seen_keys.add(identity)
                if job.source_metadata.get("listing_location_missing") is True:
                    missing_location_count += 1
                if job.published_at_raw is None:
                    missing_date_count += 1
                else:
                    relative_date_count += 1
                jobs.append(job)

            raw_job_count += len(raw_jobs)
            if raw_job_count >= expected_total:
                break
        else:
            diagnostics.append(
                _diagnostic(
                    "pagination_limit",
                    DiagnosticSeverity.ERROR,
                    "Workday pagination exceeded the configured page limit.",
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

        if relative_date_count:
            diagnostics.append(
                _diagnostic(
                    "relative_posted_on",
                    DiagnosticSeverity.WARNING,
                    "Workday relative postedOn labels are retained as uncertain date evidence.",
                    count=relative_date_count,
                )
            )
        if missing_location_count:
            diagnostics.append(
                _diagnostic(
                    "missing_location",
                    DiagnosticSeverity.WARNING,
                    "Workday listings without list-page locations require detail retrieval.",
                    count=missing_location_count,
                )
            )
        if missing_date_count:
            diagnostics.append(
                _diagnostic(
                    "missing_publication_date",
                    DiagnosticSeverity.WARNING,
                    "Workday listings without postedOn remain explicit missing date evidence.",
                    count=missing_date_count,
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
        """Retrieve one public detail payload and enrich its normalized listing."""
        parameters = _workday_parameters(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Workday detail job does not match the configured source.")
        external_path = job.source_metadata.get("external_path")
        if not isinstance(external_path, str) or not external_path.startswith("/job/"):
            raise ValueError("Workday detail job requires its public external_path metadata.")
        response = self._client.get(
            _api_base(parameters) + external_path,
            accepted_content_types=("application/json",),
        )
        try:
            payload: Any = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Workday detail response was not valid JSON.") from error
        if not isinstance(payload, Mapping):
            raise ValueError("Workday detail response root must be an object.")
        info = payload.get("jobPostingInfo")
        if not isinstance(info, Mapping):
            raise ValueError("Workday detail response requires a jobPostingInfo object.")
        title = _required_string(info, "title")
        primary_location = _required_string(info, "location")
        additional_locations = _string_list(info.get("additionalLocations"))
        locations = [primary_location, *additional_locations]
        description = _plain_text(_required_string(info, "jobDescription"))
        if not description:
            raise ValueError("Workday jobDescription must contain readable text.")
        external_id = _optional_string(info.get("jobReqId")) or job.external_job_id
        external_url = _optional_string(info.get("externalUrl"))
        canonical_url = (
            _canonical_detail_url(parameters, external_url)
            if external_url is not None
            else job.canonical_url
        )
        posted_on = _optional_string(info.get("postedOn")) or job.published_at_raw
        source_metadata = dict(job.source_metadata)
        source_metadata.update(
            {
                "additional_locations": tuple(additional_locations),
                "job_posting_id": info.get("jobPostingId"),
                "start_date_raw": _optional_string(info.get("startDate")),
                "time_type": info.get("timeType"),
            }
        )
        return NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=self.adapter_type.value,
            external_job_id=external_id,
            title_original=title,
            title_normalized=_normalize_text(title),
            location_original=" | ".join(_unique_strings(locations)),
            location_normalized=_normalized_locations(locations),
            published_at=None,
            published_at_raw=posted_on,
            date_basis=DateBasis.UNKNOWN,
            canonical_url=canonical_url,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=source_metadata,
        )


def _workday_parameters(source: CompanySource) -> Mapping[str, str]:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.WORKDAY,
        required_parameters=("host", "tenant", "site"),
    )
    host = parameters["host"].lower()
    tenant = parameters["tenant"]
    if (
        not host.endswith(".myworkdayjobs.com")
        or host.split(".", maxsplit=1)[0].casefold() != tenant.casefold()
        or urlsplit(f"https://{host}").hostname != host
    ):
        raise ValueError("Workday host must be the configured tenant's public jobs host.")
    return parameters


def _api_base(parameters: Mapping[str, str]) -> str:
    return (
        f"https://{parameters['host'].lower()}/wday/cxs/"
        f"{quote(parameters['tenant'], safe='')}/{quote(parameters['site'], safe='')}"
    )


def _normalize_listing(
    source: CompanySource,
    parameters: Mapping[str, str],
    raw_job: object,
) -> NormalizedJob:
    if not isinstance(raw_job, Mapping):
        raise ValueError("Workday job must be an object.")
    title = _required_string(raw_job, "title")
    external_path = _required_string(raw_job, "externalPath")
    if not external_path.startswith("/job/"):
        raise ValueError("Workday externalPath must start with /job/.")
    location_value = _optional_string(raw_job.get("locationsText"))
    location = location_value or "Location unavailable"
    posted_on = _optional_string(raw_job.get("postedOn"))
    bullet_fields = _string_list(raw_job.get("bulletFields"))
    external_id = bullet_fields[0] if bullet_fields else _id_from_path(external_path)
    canonical_url = (
        f"https://{parameters['host'].lower()}/{quote(parameters['site'], safe='')}{external_path}"
    )
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.WORKDAY.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=_normalize_text(title),
        location_original=location,
        location_normalized=_normalized_locations((location,)),
        published_at=None,
        published_at_raw=posted_on,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        source_metadata={
            "external_path": external_path,
            "bullet_fields": tuple(bullet_fields),
            "time_type": raw_job.get("timeType"),
            "detail_available": True,
            "listing_location_missing": location_value is None,
        },
    )


def _canonical_detail_url(parameters: Mapping[str, str], value: str) -> str:
    parsed = urlsplit(value)
    expected_host = parameters["host"].lower()
    expected_prefix = f"/{parameters['site']}/job/"
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != expected_host
        or not parsed.path.startswith(expected_prefix)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Workday externalUrl must be a job on the configured public board.")
    return f"https://{expected_host}{parsed.path.rstrip('/')}"


def _schema_failure(
    source: CompanySource,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    message: str,
    page_index: int,
) -> AdapterResult:
    diagnostics.append(
        _diagnostic(
            "unsupported_schema",
            DiagnosticSeverity.ERROR,
            message,
            page_index=page_index,
        )
    )
    return _result(
        source,
        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
        jobs,
        page_count,
        diagnostics,
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
        raise ValueError(f"Workday job field {key} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("Workday string-list field must contain only non-empty strings.")
    return [item.strip() for item in value if isinstance(item, str)]


def _id_from_path(external_path: str) -> str | None:
    final_segment = external_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    _, separator, candidate = final_segment.rpartition("_")
    return candidate if separator and candidate else None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalized_locations(locations: Iterable[str]) -> tuple[str, ...]:
    parts: list[str] = []
    for location in locations:
        parts.extend(
            piece
            for piece in re.split(r"[,|;/]|\bor\b", location, flags=re.IGNORECASE)
            if piece.strip()
        )
    return tuple(_unique_strings(_normalize_text(piece) for piece in parts))


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
