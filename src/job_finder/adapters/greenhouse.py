"""Adapter for Greenhouse's public Job Board API."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

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

GREENHOUSE_JOBS_API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"


class GreenhouseAdapter:
    """Retrieve one complete Greenhouse board with descriptions included."""

    adapter_type = AdapterType.GREENHOUSE

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        parameters = require_source_configuration(
            source,
            adapter_type=self.adapter_type,
            required_parameters=("board_token",),
        )
        endpoint = GREENHOUSE_JOBS_API.format(board_token=quote(parameters["board_token"], safe=""))
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
            return _failed_result(
                source,
                "invalid_json",
                "Greenhouse response was not valid JSON.",
            )
        if not isinstance(payload, Mapping):
            return _failed_result(
                source,
                "unsupported_schema",
                "Greenhouse response root must be an object.",
            )
        raw_jobs = payload.get("jobs")
        meta = payload.get("meta")
        if not isinstance(raw_jobs, list) or not isinstance(meta, Mapping):
            return _failed_result(
                source,
                "missing_jobs_collection",
                "Greenhouse response requires jobs and meta objects.",
            )
        total = meta.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            return _failed_result(
                source,
                "invalid_total",
                "Greenhouse meta.total must be a non-negative integer.",
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        duplicate_count = 0
        parse_error_count = 0
        for index, raw_job in enumerate(raw_jobs):
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

        if total != len(raw_jobs):
            diagnostics.append(
                AdapterDiagnostic(
                    category="incomplete_collection",
                    severity=DiagnosticSeverity.ERROR,
                    message="Greenhouse meta.total does not match the returned jobs collection.",
                    context={"expected": str(total), "observed": str(len(raw_jobs))},
                )
            )
        if duplicate_count:
            diagnostics.append(
                AdapterDiagnostic(
                    category="duplicate_job_id",
                    severity=DiagnosticSeverity.ERROR,
                    message="Greenhouse response contained duplicate job IDs.",
                    context={"count": str(duplicate_count)},
                )
            )
        if total != len(raw_jobs) or duplicate_count:
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
            return AdapterResult(
                schema_version=1,
                source=source,
                outcome=AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
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
        raise ValueError("Greenhouse job must be an object.")
    external_id = _required_identifier(raw_job, "id")
    title = _required_string(raw_job, "title")
    location = raw_job.get("location")
    if not isinstance(location, Mapping):
        raise ValueError("Greenhouse job field location must be an object.")
    primary_location = _required_string(location, "name")
    locations = [primary_location, *_office_locations(raw_job.get("offices"))]
    job_url = _canonical_url(_required_string(raw_job, "absolute_url"))
    description = _plain_text(_required_string(raw_job, "content"))
    if not description:
        raise ValueError("Greenhouse job content must contain readable text.")

    first_published_raw = _optional_string(raw_job.get("first_published"))
    updated_raw = _optional_string(raw_job.get("updated_at"))
    first_published = _parse_timestamp(first_published_raw)
    updated = _parse_timestamp(updated_raw)
    warnings: list[AdapterDiagnostic] = []
    if first_published is not None:
        published_at = first_published
        published_at_raw = first_published_raw
        date_basis = DateBasis.PUBLISHED
    elif updated is not None:
        published_at = updated
        published_at_raw = updated_raw
        date_basis = DateBasis.UPDATED
        warnings.append(
            AdapterDiagnostic(
                category="updated_date_fallback",
                severity=DiagnosticSeverity.WARNING,
                message="Greenhouse first_published was unavailable; updated_at was retained.",
                context={"job_index": str(index), "job_id": external_id},
            )
        )
    else:
        published_at = None
        published_at_raw = first_published_raw or updated_raw
        date_basis = DateBasis.UNKNOWN
        warnings.append(
            AdapterDiagnostic(
                category="uncertain_publication_date",
                severity=DiagnosticSeverity.WARNING,
                message="Greenhouse publication and update dates were missing or invalid.",
                context={"job_index": str(index), "job_id": external_id},
            )
        )

    return (
        NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=AdapterType.GREENHOUSE.value,
            external_job_id=external_id,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=" | ".join(_unique_strings(locations)),
            location_normalized=_shared_locations(locations),
            published_at=published_at,
            published_at_raw=published_at_raw,
            date_basis=date_basis,
            canonical_url=job_url,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata={
                "internal_job_id": raw_job.get("internal_job_id"),
                "language": raw_job.get("language"),
                "application_deadline": raw_job.get("application_deadline"),
                "first_published_raw": first_published_raw,
                "updated_at_raw": updated_raw,
                "departments": tuple(_names(raw_job.get("departments"))),
                "offices": tuple(_names(raw_job.get("offices"))),
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


def _required_string(raw: Mapping[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Greenhouse job field {key} must be a non-empty string.")
    return value.strip()


def _required_identifier(raw: Mapping[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).strip():
        raise ValueError(f"Greenhouse job field {key} must be a string or integer identifier.")
    return str(value).strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        name.strip()
        for item in value
        if isinstance(item, Mapping)
        and isinstance((name := item.get("name")), str)
        and name.strip()
    ]


def _office_locations(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        location.strip()
        for item in value
        if isinstance(item, Mapping)
        and isinstance((location := item.get("location")), str)
        and location.strip()
    ]


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Greenhouse absolute_url must be an absolute public HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Greenhouse absolute_url must not contain credentials.")
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"gh_src", "source", "ref", "referrer"}
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), query, ""))


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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
