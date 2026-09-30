"""Adapter for Eightfold's public candidate-career APIs."""

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
from urllib.parse import quote, urlsplit

from job_finder.adapters._support import diagnostic, unique_strings
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
from job_finder.core.validation import clean_optional, required_string
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_title,
)

DEFAULT_PAGE_SIZE = 10
DEFAULT_MAX_PAGES = 500
_TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$", re.IGNORECASE)


class EightfoldAdapter:
    """Retrieve complete Eightfold listings and optional public job details."""

    adapter_type = AdapterType.EIGHTFOLD

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

        for page_index in range(self._max_pages):
            endpoint = _api_base(tenant) + f"/jobs?start={raw_job_count}&num={self._page_size}"
            try:
                response = self._client.get(
                    endpoint,
                    accepted_content_types=("application/json",),
                    referer=_careers_url(tenant),
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
                raw_jobs, total = _listing_collection(payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                diagnostics.append(
                    diagnostic(
                        "invalid_json",
                        DiagnosticSeverity.ERROR,
                        "Eightfold response was not valid JSON.",
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
            except ValueError as error:
                return _schema_failure(
                    source,
                    jobs,
                    page_count,
                    diagnostics,
                    str(error),
                    page_index,
                )

            if len(raw_jobs) > self._page_size:
                diagnostics.append(
                    diagnostic(
                        "page_size_exceeded",
                        DiagnosticSeverity.ERROR,
                        "Eightfold returned more jobs than the requested page limit.",
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
            elif total != expected_total:
                diagnostics.append(
                    diagnostic(
                        "inconsistent_total",
                        DiagnosticSeverity.ERROR,
                        "Eightfold count changed during pagination; completeness is unknown.",
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
                    diagnostic(
                        "repeated_page",
                        DiagnosticSeverity.ERROR,
                        "Eightfold returned a repeated non-empty page.",
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
                    diagnostic(
                        "collection_exceeds_total",
                        DiagnosticSeverity.ERROR,
                        "Eightfold returned more jobs than the first-page count.",
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
                    diagnostic(
                        "premature_empty_page",
                        DiagnosticSeverity.ERROR,
                        "Eightfold returned an empty page before the reported count.",
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
                    job = _normalize_job(source, tenant, raw_job)
                except ValueError as error:
                    parse_error_count += 1
                    diagnostics.append(
                        diagnostic(
                            "malformed_job",
                            DiagnosticSeverity.ERROR,
                            str(error),
                            page_index=page_index,
                            job_index=job_index,
                        )
                    )
                    continue
                if job.external_job_id in seen_ids:
                    diagnostics.append(
                        diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "Eightfold pagination returned a duplicate job ID.",
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
                diagnostic(
                    "pagination_limit",
                    DiagnosticSeverity.ERROR,
                    "Eightfold pagination exceeded the configured page limit.",
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
                diagnostic(
                    "unverified_t_create",
                    DiagnosticSeverity.WARNING,
                    "Eightfold t_create is retained as uncertain date evidence.",
                    count=uncertain_date_count,
                )
            )
        if missing_date_count:
            diagnostics.append(
                diagnostic(
                    "missing_publication_date",
                    DiagnosticSeverity.WARNING,
                    "Eightfold listings without t_create remain explicit.",
                    count=missing_date_count,
                )
            )
        if missing_location_count:
            diagnostics.append(
                diagnostic(
                    "missing_location",
                    DiagnosticSeverity.WARNING,
                    "Eightfold listings without locations remain explicit.",
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
        """Retrieve one public Eightfold detail payload without changing identity."""
        tenant = _tenant(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Eightfold detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("Eightfold detail retrieval requires an external job ID.")
        response = self._client.get(
            _api_base(tenant) + "/jobs/" + quote(job.external_job_id, safe=""),
            accepted_content_types=("application/json",),
            referer=job.canonical_url,
        )
        try:
            payload: Any = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Eightfold detail response was not valid JSON.") from error
        detail = _job_mapping(payload, "Eightfold detail response root")
        normalized = _normalize_job(source, tenant, detail)
        if normalized.external_job_id != job.external_job_id:
            raise ValueError("Eightfold detail response job ID does not match the listing.")
        return normalized


def _tenant(source: CompanySource) -> str:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.EIGHTFOLD,
        required_parameters=("tenant",),
    )
    tenant = parameters["tenant"].strip().lower()
    if not _TENANT_PATTERN.fullmatch(tenant):
        raise ValueError("Eightfold tenant must contain only letters, digits, and hyphens.")
    if tenant == "app":
        raise ValueError("Shared Eightfold app host requires an explicit company mapping.")
    return tenant


def _host(tenant: str) -> str:
    return f"{tenant}.eightfold.ai"


def _api_base(tenant: str) -> str:
    return f"https://{_host(tenant)}/api/apply/v2"


def _careers_url(tenant: str) -> str:
    return f"https://{_host(tenant)}/careers"


def _listing_collection(payload: object) -> tuple[list[object], int]:
    root = _job_mapping(payload, "Eightfold response root")
    positions = root.get("positions")
    count = root.get("count")
    if not isinstance(positions, list):
        raise ValueError("Eightfold response requires a positions array.")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("Eightfold count must be a non-negative integer.")
    return positions, count


def _normalize_job(
    source: CompanySource,
    tenant: str,
    raw_job: object,
) -> NormalizedJob:
    job = _job_mapping(raw_job, "Eightfold job")
    external_id = _identifier(job.get("id"))
    title = clean_optional(job.get("name")) or required_string(job, "posting_name")
    locations = _locations(job)
    location_missing = not locations
    if location_missing:
        locations = ["Location unavailable"]
    description_html = clean_optional(job.get("job_description"))
    description = _plain_text(description_html) if description_html is not None else None
    if not description:
        description = None
    canonical_url = _canonical_url(job.get("canonicalPositionUrl"), tenant, external_id)
    t_create = job.get("t_create")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.EIGHTFOLD.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=" | ".join(unique_strings(locations)),
        location_normalized=_shared_locations(locations),
        published_at=_parse_epoch(t_create),
        published_at_raw=_raw_date(t_create),
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        description=description,
        description_hash=(
            hashlib.sha256(description.encode("utf-8")).hexdigest()
            if description is not None
            else None
        ),
        source_metadata={
            "ats_job_id": job.get("ats_job_id"),
            "business_unit": job.get("business_unit"),
            "department": job.get("department"),
            "display_job_id": job.get("display_job_id"),
            "listing_location_missing": location_missing,
            "t_update_raw": _raw_date(job.get("t_update")),
            "work_location_option": job.get("work_location_option"),
        },
    )


def _job_mapping(value: object, label: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object.")
    return value


def _identifier(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError("Eightfold job field id must be a non-negative integer or string.")


def _canonical_url(value: object, tenant: str, external_id: str) -> str:
    candidate = clean_optional(value)
    if candidate is not None:
        parsed = urlsplit(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return candidate
    return _careers_url(tenant) + "/job/" + quote(external_id, safe="")


def _locations(job: Mapping[object, object]) -> list[str]:
    raw_locations = job.get("locations")
    if isinstance(raw_locations, list):
        locations = [
            item.strip() for item in raw_locations if isinstance(item, str) and item.strip()
        ]
        if locations:
            return locations
    location = clean_optional(job.get("location"))
    return [location] if location is not None else []


def _raw_date(value: object) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_epoch(value: object) -> datetime | None:
    numeric: float
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    if numeric >= 100_000_000_000:
        numeric /= 1000
    try:
        return datetime.fromtimestamp(numeric, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


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


def _schema_failure(
    source: CompanySource,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    message: str,
    page_index: int,
) -> AdapterResult:
    diagnostics.append(
        diagnostic(
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
