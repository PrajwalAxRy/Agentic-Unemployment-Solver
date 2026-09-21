"""Adapter for SmartRecruiters' public postings API."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

from job_finder.adapters.base import request_failure_diagnostic, require_source_configuration
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

SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100


class SmartRecruitersAdapter:
    """Retrieve public SmartRecruiters postings with count-checked offset pagination."""

    adapter_type = AdapterType.SMARTRECRUITERS

    def __init__(
        self,
        client: BoundedHttpClient | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if page_size <= 0 or max_pages <= 0:
            raise ValueError("page_size and max_pages must be positive")
        self._client = client or BoundedHttpClient()
        self._page_size = page_size
        self._max_pages = max_pages

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        parameters = require_source_configuration(
            source, adapter_type=self.adapter_type, required_parameters=("company_identifier",)
        )
        company = _company_identifier(parameters["company_identifier"])
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None

        for page_index in range(self._max_pages):
            offset = page_index * self._page_size
            endpoint = (
                f"{SMARTRECRUITERS_API.format(company=quote(company, safe=''))}"
                f"?limit={self._page_size}&offset={offset}"
            )
            try:
                response = self._client.get(endpoint, accepted_content_types=("application/json",))
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    page_index,
                    diagnostics,
                )
            try:
                payload: Any = json.loads(response.body)
                content, total = _page(payload)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
                diagnostics.append(_diagnostic("unsupported_schema", str(error), page_index))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_index + 1,
                    diagnostics,
                )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                diagnostics.append(
                    _diagnostic(
                        "inconsistent_total",
                        "SmartRecruiters totalFound changed during pagination.",
                        page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)
            if len(content) > self._page_size:
                diagnostics.append(
                    _diagnostic(
                        "page_size_exceeded",
                        "SmartRecruiters returned more jobs than requested.",
                        page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)
            for job_index, raw in enumerate(content):
                try:
                    job, warnings = _normalize_job(source, raw, page_index, job_index)
                except ValueError as error:
                    diagnostics.append(
                        _diagnostic("malformed_job", str(error), page_index, job_index)
                    )
                    continue
                diagnostics.extend(warnings)
                if job.external_job_id in seen_ids:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            "SmartRecruiters returned a duplicate job ID.",
                            page_index,
                            job_index,
                        )
                    )
                    return _result(
                        source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics
                    )
                if job.external_job_id is not None:
                    seen_ids.add(job.external_job_id)
                jobs.append(job)
            if len(jobs) == total:
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    complete=True,
                )
            if len(content) < self._page_size or len(jobs) > total:
                diagnostics.append(
                    _diagnostic(
                        "incomplete_pagination",
                        "SmartRecruiters content did not match totalFound.",
                        page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)
        diagnostics.append(
            _diagnostic(
                "pagination_limit",
                "SmartRecruiters pagination reached its configured page limit.",
                self._max_pages,
            )
        )
        return _result(source, AdapterOutcome.SUSPICIOUS, jobs, self._max_pages, diagnostics)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        parameters = require_source_configuration(
            source, adapter_type=self.adapter_type, required_parameters=("company_identifier",)
        )
        if job.external_job_id is None:
            raise ValueError("SmartRecruiters detail retrieval requires an external job ID.")
        company = _company_identifier(parameters["company_identifier"])
        endpoint = (
            SMARTRECRUITERS_API.format(company=quote(company, safe=""))
            + "/"
            + quote(job.external_job_id, safe="")
        )
        response = self._client.get(endpoint, accepted_content_types=("application/json",))
        try:
            payload: Any = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("SmartRecruiters detail response was not valid JSON.") from error
        if (
            not isinstance(payload, Mapping)
            or _required_string(payload, "id") != job.external_job_id
        ):
            raise ValueError("SmartRecruiters detail response job ID does not match the listing.")
        description = _detail_description(payload)
        return replace(
            job,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest()
            if description
            else None,
        )


def _page(payload: object) -> tuple[list[object], int]:
    if not isinstance(payload, Mapping):
        raise ValueError("SmartRecruiters response root must be an object.")
    content, total = payload.get("content"), payload.get("totalFound")
    if (
        not isinstance(content, list)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
    ):
        raise ValueError("SmartRecruiters response requires content and non-negative totalFound.")
    return content, total


def _normalize_job(
    source: CompanySource, raw: object, page_index: int, job_index: int
) -> tuple[NormalizedJob, tuple[AdapterDiagnostic, ...]]:
    if not isinstance(raw, Mapping):
        raise ValueError("SmartRecruiters job must be an object.")
    external_id, title = _required_string(raw, "id"), _required_string(raw, "name")
    location = raw.get("location")
    if not isinstance(location, Mapping):
        raise ValueError("SmartRecruiters job location must be an object.")
    original = _required_string(location, "fullLocation")
    published_raw = _optional_string(raw.get("releasedDate"))
    published_at = _parse_timestamp(published_raw)
    warnings: list[AdapterDiagnostic] = []
    if published_at is None:
        warnings.append(
            _diagnostic(
                "uncertain_publication_date",
                "SmartRecruiters releasedDate was missing or invalid.",
                page_index,
                job_index,
            )
        )
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.SMARTRECRUITERS.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=_normalize(title),
        location_original=original,
        location_normalized=_locations(original),
        published_at=published_at,
        published_at_raw=published_raw,
        date_basis=DateBasis.PUBLISHED if published_at else DateBasis.UNKNOWN,
        canonical_url=_canonical_url(raw.get("ref"), external_id),
        description=None,
        description_hash=None,
        source_metadata={
            "uuid": raw.get("uuid"),
            "remote": location.get("remote"),
            "hybrid": location.get("hybrid"),
        },
    ), tuple(warnings)


def _detail_description(payload: Mapping[object, object]) -> str | None:
    job_ad = payload.get("jobAd")
    if not isinstance(job_ad, Mapping):
        return None
    sections = job_ad.get("sections")
    if not isinstance(sections, Mapping):
        return None
    text = "\n\n".join(
        value.strip() for value in sections.values() if isinstance(value, str) and value.strip()
    )
    return text or None


def _canonical_url(value: object, external_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("SmartRecruiters job field ref must be a non-empty URL.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.smartrecruiters.com"
        or not parsed.path.endswith("/" + external_id)
    ):
        raise ValueError("SmartRecruiters job ref must use the public API URL for its ID.")
    parts = parsed.path.split("/")
    return f"https://jobs.smartrecruiters.com/{parts[-3]}/{external_id}"


def _company_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]+", value):
        raise ValueError(
            "SmartRecruiters company_identifier must contain only letters, digits, and hyphens."
        )
    return value


def _required_string(raw: Mapping[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"SmartRecruiters job field {key} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.tzinfo else None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _locations(value: str) -> tuple[str, ...]:
    result = tuple(_normalize(item) for item in re.split(r"[,|;/]", value) if item.strip())
    return result or ("location unavailable",)


def _diagnostic(
    category: str, message: str, page_index: int, job_index: int | None = None
) -> AdapterDiagnostic:
    context = {"page_index": str(page_index)}
    if job_index is not None:
        context["job_index"] = str(job_index)
    return AdapterDiagnostic(
        category=category,
        severity=DiagnosticSeverity.ERROR
        if category not in {"uncertain_publication_date"}
        else DiagnosticSeverity.WARNING,
        message=message,
        context=context,
    )


def _request_outcome(error: HttpRequestError) -> AdapterOutcome:
    return (
        AdapterOutcome.BLOCKED
        if error.category is HttpFailureCategory.ACCESS_BLOCK
        else AdapterOutcome.FAILED
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
