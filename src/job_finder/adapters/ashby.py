"""Adapter for Ashby's public job-posting API."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from job_finder.adapters._support import unique_strings
from job_finder.adapters.base import (
    request_failure_diagnostic,
    require_source_configuration,
)
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
from job_finder.core.validation import clean_optional, required_string
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_title,
)

ASHBY_POSTING_API = "https://api.ashbyhq.com/posting-api/job-board/{board_name}"


class AshbyAdapter:
    """Retrieve and normalize one complete public Ashby job-board collection."""

    adapter_type = AdapterType.ASHBY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        parameters = require_source_configuration(
            source,
            adapter_type=self.adapter_type,
            required_parameters=("board_name",),
        )
        endpoint = ASHBY_POSTING_API.format(board_name=quote(parameters["board_name"], safe=""))
        try:
            response = self._client.get(
                endpoint,
                accepted_content_types=("application/json",),
            )
        except HttpRequestError as error:
            outcome = (
                AdapterOutcome.BLOCKED
                if error.category is HttpFailureCategory.ACCESS_BLOCK
                else AdapterOutcome.FAILED
            )
            return AdapterResult(
                schema_version=1,
                source=source,
                outcome=outcome,
                jobs=(),
                page_count=0,
                complete=False,
                diagnostics=(request_failure_diagnostic(error),),
            )

        try:
            payload: Any = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _failed_result(source, "invalid_json", "Ashby response was not valid JSON.")
        if not isinstance(payload, Mapping) or payload.get("apiVersion") not in {1, "1"}:
            return _failed_result(
                source,
                "unsupported_schema",
                "Ashby response has an unsupported or missing apiVersion.",
            )
        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            return _failed_result(
                source,
                "missing_jobs_collection",
                "Ashby response does not contain a jobs array.",
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        skipped_unlisted = 0
        duplicate_count = 0
        parse_error_count = 0
        for index, raw_job in enumerate(raw_jobs):
            if isinstance(raw_job, Mapping) and raw_job.get("isListed") is False:
                skipped_unlisted += 1
                continue
            try:
                job, warnings = _normalize_job(source, raw_job, index=index)
            except ValueError as error:
                parse_error_count += 1
                diagnostics.append(
                    AdapterDiagnostic(
                        category="malformed_job",
                        severity=DiagnosticSeverity.ERROR,
                        message=str(error),
                        context={"job_index": str(index)},
                    )
                )
                continue
            diagnostics.extend(warnings)
            if job.external_job_id in seen_ids:
                duplicate_count += 1
                continue
            if job.external_job_id is not None:
                seen_ids.add(job.external_job_id)
            jobs.append(job)

        if skipped_unlisted:
            diagnostics.append(
                AdapterDiagnostic(
                    category="unlisted_jobs_skipped",
                    severity=DiagnosticSeverity.INFO,
                    message="Ashby jobs marked isListed=false were excluded.",
                    context={"count": str(skipped_unlisted)},
                )
            )
        if duplicate_count:
            diagnostics.append(
                AdapterDiagnostic(
                    category="duplicate_job_id",
                    severity=DiagnosticSeverity.ERROR,
                    message="Ashby response contained duplicate job IDs.",
                    context={"count": str(duplicate_count)},
                )
            )
            return AdapterResult(
                schema_version=1,
                source=source,
                outcome=AdapterOutcome.SUSPICIOUS,
                jobs=tuple(jobs),
                page_count=1,
                complete=False,
                diagnostics=tuple(diagnostics),
            )
        if parse_error_count:
            outcome = AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED
            return AdapterResult(
                schema_version=1,
                source=source,
                outcome=outcome,
                jobs=tuple(jobs),
                page_count=1,
                complete=False,
                diagnostics=tuple(diagnostics),
            )
        return AdapterResult(
            schema_version=1,
            source=source,
            outcome=AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs=tuple(jobs),
            page_count=1,
            complete=True,
            diagnostics=tuple(diagnostics),
        )


def _normalize_job(
    source: CompanySource,
    raw_job: object,
    *,
    index: int,
) -> tuple[NormalizedJob, tuple[AdapterDiagnostic, ...]]:
    if not isinstance(raw_job, Mapping):
        raise ValueError("Ashby job must be an object.")
    external_id = required_string(raw_job, "id")
    title = required_string(raw_job, "title")
    primary_location = required_string(raw_job, "location")
    job_url = _canonical_ashby_url(required_string(raw_job, "jobUrl"))
    description = required_string(raw_job, "descriptionPlain")
    locations = [primary_location, *_secondary_locations(raw_job.get("secondaryLocations"))]
    if raw_job.get("isRemote") is True or raw_job.get("workplaceType") == "Remote":
        locations.append("Remote")
    location_original = " | ".join(unique_strings(locations))

    published_raw = clean_optional(raw_job.get("publishedAt"))
    published_at = _parse_timestamp(published_raw)
    warnings: list[AdapterDiagnostic] = []
    date_basis = DateBasis.PUBLISHED if published_at is not None else DateBasis.UNKNOWN
    if published_at is None:
        warnings.append(
            AdapterDiagnostic(
                category="uncertain_publication_date",
                severity=DiagnosticSeverity.WARNING,
                message="Ashby publishedAt was missing or invalid.",
                context={"job_index": str(index), "job_id": external_id},
            )
        )

    description = description.strip()
    return (
        NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=AdapterType.ASHBY.value,
            external_job_id=external_id,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=location_original,
            location_normalized=_shared_locations(locations),
            published_at=published_at,
            published_at_raw=published_raw,
            date_basis=date_basis,
            canonical_url=job_url,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata={
                "api_version": "1",
                "is_listed": raw_job.get("isListed"),
                "is_remote": raw_job.get("isRemote"),
                "workplace_type": raw_job.get("workplaceType"),
                "employment_type": raw_job.get("employmentType"),
                "department": raw_job.get("department"),
                "team": raw_job.get("team"),
            },
        ),
        tuple(warnings),
    )


def _failed_result(source: CompanySource, category: str, message: str) -> AdapterResult:
    return AdapterResult(
        schema_version=1,
        source=source,
        outcome=AdapterOutcome.FAILED,
        jobs=(),
        page_count=1,
        complete=False,
        diagnostics=(
            AdapterDiagnostic(
                category=category,
                severity=DiagnosticSeverity.ERROR,
                message=message,
                context={},
            ),
        ),
    )


def _secondary_locations(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Ashby job field secondaryLocations must be an array.")
    locations: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("Ashby secondary location must be an object.")
        location = item.get("location")
        if not isinstance(location, str) or not location.strip():
            raise ValueError("Ashby secondary location requires a location string.")
        locations.append(location.strip())
    return locations


def _canonical_ashby_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "jobs.ashbyhq.com":
        raise ValueError("Ashby jobUrl must use the public jobs.ashbyhq.com HTTPS host.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
