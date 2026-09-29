"""Adapter for Lever's public Postings API."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from job_finder.adapters._support import unique_strings
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

LEVER_POSTINGS_API = "https://api.lever.co/v0/postings/{site}?mode=json&skip={skip}&limit={limit}"
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100


class LeverAdapter:
    """Retrieve every public Lever posting using bounded skip/limit pagination."""

    adapter_type = AdapterType.LEVER

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
        parameters = require_source_configuration(
            source,
            adapter_type=self.adapter_type,
            required_parameters=("site",),
        )
        site = quote(parameters["site"], safe="")
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()
        duplicate_count = 0
        parse_error_count = 0
        page_count = 0

        for page_index in range(self._max_pages):
            endpoint = LEVER_POSTINGS_API.format(
                site=site,
                skip=page_index * self._page_size,
                limit=self._page_size,
            )
            try:
                response = self._client.get(
                    endpoint,
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
                        "Lever response was not valid JSON.",
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
            if not isinstance(payload, list):
                diagnostics.append(
                    _diagnostic(
                        "unsupported_schema",
                        DiagnosticSeverity.ERROR,
                        "Lever response root must be an array.",
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
            if len(payload) > self._page_size:
                diagnostics.append(
                    _diagnostic(
                        "page_size_exceeded",
                        DiagnosticSeverity.ERROR,
                        "Lever returned more jobs than the requested page limit.",
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

            page_fingerprint = hashlib.sha256(response.body).hexdigest()
            if payload and page_fingerprint in seen_pages:
                diagnostics.append(
                    _diagnostic(
                        "repeated_page",
                        DiagnosticSeverity.ERROR,
                        "Lever returned a repeated non-empty page; completeness is unknown.",
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
            seen_pages.add(page_fingerprint)

            for job_index, raw_job in enumerate(payload):
                try:
                    job, warnings = _normalize_job(
                        source,
                        raw_job,
                        page_index=page_index,
                        job_index=job_index,
                    )
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
                diagnostics.extend(warnings)
                if job.external_job_id in seen_ids:
                    duplicate_count += 1
                    continue
                if job.external_job_id is not None:
                    seen_ids.add(job.external_job_id)
                jobs.append(job)

            if len(payload) < self._page_size:
                if duplicate_count:
                    diagnostics.append(
                        AdapterDiagnostic(
                            category="duplicate_job_id",
                            severity=DiagnosticSeverity.ERROR,
                            message="Lever pages contained duplicate job IDs.",
                            context={"count": str(duplicate_count)},
                        )
                    )
                    return _result(
                        source,
                        AdapterOutcome.SUSPICIOUS,
                        jobs,
                        page_count,
                        diagnostics,
                    )
                if parse_error_count:
                    outcome = AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED
                    return _result(source, outcome, jobs, page_count, diagnostics)
                outcome = AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY
                return _result(source, outcome, jobs, page_count, diagnostics, complete=True)

        diagnostics.append(
            AdapterDiagnostic(
                category="pagination_limit",
                severity=DiagnosticSeverity.ERROR,
                message="Lever pagination reached the configured page limit.",
                context={"max_pages": str(self._max_pages)},
            )
        )
        return _result(
            source,
            AdapterOutcome.SUSPICIOUS,
            jobs,
            page_count,
            diagnostics,
        )


def _normalize_job(
    source: CompanySource,
    raw_job: object,
    *,
    page_index: int,
    job_index: int,
) -> tuple[NormalizedJob, tuple[AdapterDiagnostic, ...]]:
    if not isinstance(raw_job, Mapping):
        raise ValueError("Lever job must be an object.")
    external_id = _required_string(raw_job, "id")
    title = _required_string(raw_job, "text")
    categories = raw_job.get("categories")
    if not isinstance(categories, Mapping):
        raise ValueError("Lever job field categories must be an object.")
    primary_location = _required_string(categories, "location")
    locations = [primary_location, *_string_list(categories.get("allLocations"), "allLocations")]
    workplace_type = _optional_string(raw_job.get("workplaceType"))
    if workplace_type is not None and workplace_type.casefold() == "remote":
        locations.append("Remote")
    description = _description(raw_job)
    hosted_url = _canonical_lever_url(_required_string(raw_job, "hostedUrl"))

    created_at_raw = raw_job.get("createdAt")
    created_at = _parse_epoch_milliseconds(created_at_raw)
    warnings: list[AdapterDiagnostic] = []
    if created_at is None:
        date_warning = AdapterDiagnostic(
            category="uncertain_publication_date",
            severity=DiagnosticSeverity.WARNING,
            message="Lever exposes no verified publication date for this job.",
            context={
                "page_index": str(page_index),
                "job_index": str(job_index),
                "job_id": external_id,
            },
        )
    else:
        date_warning = AdapterDiagnostic(
            category="unverified_created_at",
            severity=DiagnosticSeverity.WARNING,
            message=(
                "Lever createdAt was retained, but public documentation does not establish it "
                "as the publication time."
            ),
            context={
                "page_index": str(page_index),
                "job_index": str(job_index),
                "job_id": external_id,
            },
        )

    warnings.append(date_warning)
    if description is None:
        warnings.append(
            AdapterDiagnostic(
                category="missing_description",
                severity=DiagnosticSeverity.WARNING,
                message="Lever public listing and detail fields contain no description content.",
                context={
                    "page_index": str(page_index),
                    "job_index": str(job_index),
                    "job_id": external_id,
                },
            )
        )
    return (
        NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=AdapterType.LEVER.value,
            external_job_id=external_id,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=" | ".join(unique_strings(locations)),
            location_normalized=_shared_locations(locations),
            published_at=created_at,
            published_at_raw=(str(created_at_raw) if created_at_raw is not None else None),
            date_basis=DateBasis.UNKNOWN,
            canonical_url=hosted_url,
            description=description,
            description_hash=(
                hashlib.sha256(description.encode("utf-8")).hexdigest()
                if description is not None
                else None
            ),
            source_metadata={
                "created_at_raw": created_at_raw,
                "created_at_utc": created_at.isoformat() if created_at is not None else None,
                "country": raw_job.get("country"),
                "workplace_type": workplace_type,
                "commitment": categories.get("commitment"),
                "team": categories.get("team"),
                "department": categories.get("department"),
                "apply_url": raw_job.get("applyUrl"),
            },
        ),
        tuple(warnings),
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
    *,
    page_index: int,
    job_index: int | None = None,
) -> AdapterDiagnostic:
    context = {"page_index": str(page_index)}
    if job_index is not None:
        context["job_index"] = str(job_index)
    return AdapterDiagnostic(
        category=category,
        severity=severity,
        message=message,
        context=context,
    )


def _required_string(raw: Mapping[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Lever job field {key} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _description(raw_job: Mapping[object, object]) -> str | None:
    parts: list[str] = []
    plain = _optional_string(raw_job.get("descriptionPlain"))
    if plain is not None:
        parts.append(plain)
    else:
        styled = _optional_string(raw_job.get("description"))
        if styled is not None:
            parts.append(_plain_text(styled))
    lists = raw_job.get("lists")
    if lists is not None:
        if not isinstance(lists, list):
            raise ValueError("Lever job field lists must be an array.")
        for item in lists:
            if not isinstance(item, Mapping):
                raise ValueError("Lever description list entry must be an object.")
            heading = _optional_string(item.get("text"))
            content = _optional_string(item.get("content"))
            visible = _plain_text(content) if content is not None else ""
            if visible:
                parts.append(" ".join(value for value in (heading, visible) if value))
    additional_plain = _optional_string(raw_job.get("additionalPlain"))
    if additional_plain is not None:
        parts.append(additional_plain)
    else:
        additional = _optional_string(raw_job.get("additional"))
        if additional is not None:
            parts.append(_plain_text(additional))
    combined = re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip()
    return combined or None


def _string_list(value: object, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"Lever job field {path} must be an array of non-empty strings.")
    return [item.strip() for item in value if isinstance(item, str)]


def _parse_epoch_milliseconds(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _canonical_lever_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"jobs.lever.co", "jobs.eu.lever.co"}:
        raise ValueError("Lever hostedUrl must use a public Lever HTTPS jobs host.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Lever hostedUrl must not contain credentials.")
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower()
            not in {"lever-origin", "lever-source", "source", "src", "ref", "referrer"}
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), query, ""))


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
