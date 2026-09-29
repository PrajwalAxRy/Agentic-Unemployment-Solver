"""Adapter for Oracle Cloud Recruiting Candidate Experience portals."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

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
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_title,
)

DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_PAGES = 100
API_ROOT = "/hcmRestApi/resources/latest"
LIST_RESOURCE = "recruitingCEJobRequisitions"
DETAIL_RESOURCE = "recruitingCEJobRequisitionDetails"
LIST_SORT = "POSTING_DATES_ASC"
LIST_EXPAND = (
    "requisitionList,requisitionList.workLocation,"
    "requisitionList.otherWorkLocations,requisitionList.secondaryLocations"
)


class OracleCloudAdapter:
    """Retrieve complete public Oracle Candidate Experience job inventories."""

    adapter_type = AdapterType.ORACLE_CLOUD

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
        parameters = _oracle_parameters(source)
        return self._list_snapshot(source, parameters)

    def _list_snapshot(
        self,
        source: CompanySource,
        parameters: Mapping[str, str],
    ) -> AdapterResult:
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        expected_total: int | None = None
        raw_job_count = 0
        parse_error_count = 0
        missing_date_count = 0
        missing_location_count = 0
        duplicate_count = 0
        inventory_total_changed = False
        page_count = 0
        next_offset = 0

        for page_index in range(self._max_pages):
            page_offset = next_offset
            endpoint = _list_endpoint(parameters, self._page_size, page_offset)
            try:
                response = self._client.get(
                    endpoint,
                    accepted_content_types=("application/json",),
                    referer=_board_url(parameters),
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    page_count,
                    diagnostics,
                )

            page_count += 1
            try:
                payload: Any = json.loads(response.body)
                raw_jobs, total = _search_page(
                    payload,
                    site_number=parameters["site_number"],
                    requested_limit=self._page_size,
                    requested_offset=page_offset,
                )
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
                diagnostics.append(
                    _diagnostic(
                        "unsupported_schema",
                        DiagnosticSeverity.ERROR,
                        str(error),
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

            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                diagnostics.append(
                    _diagnostic(
                        "inventory_total_changed",
                        DiagnosticSeverity.WARNING,
                        "Oracle Cloud inventory total changed during pagination; continued "
                        "through the latest reported offset range.",
                        page_index=page_index,
                        expected=expected_total,
                        observed=total,
                    )
                )
                expected_total = total
                inventory_total_changed = True

            page_ids = tuple(_raw_id(raw) for raw in raw_jobs)
            if raw_jobs and page_ids in seen_pages:
                diagnostics.append(
                    _diagnostic(
                        "repeated_page",
                        DiagnosticSeverity.ERROR,
                        "Oracle Cloud returned a repeated non-empty page.",
                        page_index=page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            seen_pages.add(page_ids)

            if page_offset + len(raw_jobs) > expected_total:
                diagnostics.append(
                    _diagnostic(
                        "collection_exceeds_total",
                        DiagnosticSeverity.ERROR,
                        "Oracle Cloud returned more jobs than the first-page total.",
                        page_index=page_index,
                        expected=expected_total,
                        observed=page_offset + len(raw_jobs),
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            if not raw_jobs and page_offset < expected_total:
                diagnostics.append(
                    _diagnostic(
                        "premature_empty_page",
                        DiagnosticSeverity.ERROR,
                        "Oracle Cloud returned an empty page before reaching its reported total.",
                        page_index=page_index,
                        expected=expected_total,
                        observed=page_offset,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)

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
                external_id = job.external_job_id
                if external_id is None:
                    raise AssertionError("Oracle Cloud normalized jobs require IDs")
                if external_id in seen_ids:
                    duplicate_count += 1
                    continue
                seen_ids.add(external_id)
                if job.published_at is None:
                    missing_date_count += 1
                if job.source_metadata.get("listing_location_missing") is True:
                    missing_location_count += 1
                jobs.append(job)

            raw_job_count += len(raw_jobs)
            next_offset += self._page_size
            if next_offset >= expected_total:
                break
            if len(raw_jobs) < self._page_size:
                diagnostics.append(
                    _diagnostic(
                        "short_page",
                        DiagnosticSeverity.WARNING,
                        "Oracle Cloud returned a short nonterminal page; pagination continued "
                        "using the requested offset range.",
                        page_index=page_index,
                        offset=page_offset,
                        expected=expected_total,
                        observed=len(raw_jobs),
                    )
                )
        else:
            diagnostics.append(
                _diagnostic(
                    "pagination_limit",
                    DiagnosticSeverity.ERROR,
                    "Oracle Cloud pagination reached its configured page limit.",
                    expected=expected_total if expected_total is not None else "unknown",
                    observed=raw_job_count,
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)

        if duplicate_count:
            diagnostics.append(
                _diagnostic(
                    "duplicate_job_id",
                    (
                        DiagnosticSeverity.WARNING
                        if inventory_total_changed
                        else DiagnosticSeverity.ERROR
                    ),
                    (
                        "Oracle Cloud active-inventory pagination repeated job IDs; each unique "
                        "listing was retained once after all requested offsets were fetched."
                        if inventory_total_changed
                        else "Oracle Cloud pagination returned duplicate job IDs without a "
                        "reported inventory change."
                    ),
                    count=duplicate_count,
                )
            )
            if not inventory_total_changed:
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    page_count,
                    diagnostics,
                )
        if missing_date_count:
            diagnostics.append(
                _diagnostic(
                    "missing_publication_date",
                    DiagnosticSeverity.WARNING,
                    "Oracle Cloud listings with missing or invalid PostedDate remain explicit.",
                    count=missing_date_count,
                )
            )
        if missing_location_count:
            diagnostics.append(
                _diagnostic(
                    "missing_location",
                    DiagnosticSeverity.WARNING,
                    "Oracle Cloud listings without a location remain available for detail review.",
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
        """Retrieve and normalize one public Oracle Cloud requisition detail."""
        parameters = _oracle_parameters(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Oracle Cloud detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("Oracle Cloud detail retrieval requires an external job ID.")

        response = self._client.get(
            _detail_endpoint(parameters, job.external_job_id),
            accepted_content_types=("application/json",),
            referer=job.canonical_url,
        )
        try:
            payload: Any = json.loads(response.body)
            detail = _detail_item(payload)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Oracle Cloud detail response was not valid job data.") from error
        detail_id = _required_string(detail, "Id")
        if detail_id != job.external_job_id:
            raise ValueError("Oracle Cloud detail response job ID does not match the listing.")

        title = _required_string(detail, "Title")
        locations = _listing_locations(detail)
        if not locations:
            locations = [job.location_original]
        description = _description(detail)
        if description is None:
            raise ValueError("Oracle Cloud detail response has no readable job description.")
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "detail_location_missing": not _listing_locations(detail),
                "external_posted_start_date": _optional_string(
                    detail.get("ExternalPostedStartDate")
                ),
                "workplace_type": detail.get("WorkplaceType"),
                "workplace_type_code": detail.get("WorkplaceTypeCode"),
            }
        )
        return replace(
            job,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=" | ".join(_unique_strings(locations)),
            location_normalized=_shared_locations(locations),
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=metadata,
        )


def _oracle_parameters(source: CompanySource) -> Mapping[str, str]:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.ORACLE_CLOUD,
        required_parameters=("host", "site_number"),
    )
    host = parameters["host"].lower()
    site_number = parameters["site_number"]
    if (
        not re.fullmatch(r"[a-z0-9.-]+", host)
        or ".." in host
        or not host.endswith(".oraclecloud.com")
        or urlsplit(f"https://{host}").hostname != host
    ):
        raise ValueError("Oracle Cloud host must be a public oraclecloud.com hostname.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", site_number):
        raise ValueError(
            "Oracle Cloud site_number must contain only letters, digits, underscores, and hyphens."
        )
    return {"host": host, "site_number": site_number}


def _board_url(parameters: Mapping[str, str]) -> str:
    return (
        f"https://{parameters['host']}/hcmUI/CandidateExperience/en/sites/"
        f"{quote(parameters['site_number'], safe='')}/jobs"
    )


def _list_endpoint(parameters: Mapping[str, str], limit: int, offset: int) -> str:
    finder = (
        f"findReqs;siteNumber={parameters['site_number']},limit={limit},offset={offset},"
        f"sortBy={LIST_SORT}"
    )
    query = urlencode({"onlyData": "true", "expand": LIST_EXPAND, "finder": finder})
    return f"https://{parameters['host']}{API_ROOT}/{LIST_RESOURCE}?{query}"


def _detail_endpoint(parameters: Mapping[str, str], external_id: str) -> str:
    finder = f'ById;Id="{external_id}",siteNumber={parameters["site_number"]}'
    query = urlencode({"expand": "all", "onlyData": "true", "finder": finder})
    return f"https://{parameters['host']}{API_ROOT}/{DETAIL_RESOURCE}?{query}"


def _search_page(
    payload: object,
    *,
    site_number: str,
    requested_limit: int,
    requested_offset: int,
) -> tuple[list[object], int]:
    if not isinstance(payload, Mapping):
        raise ValueError("Oracle Cloud response root must be an object.")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
        raise ValueError("Oracle Cloud response requires one search envelope.")
    envelope = items[0]
    total = _non_negative_int(envelope.get("TotalJobsCount"), "TotalJobsCount")
    limit = _non_negative_int(envelope.get("Limit"), "Limit")
    offset = _non_negative_int(envelope.get("Offset"), "Offset")
    if limit != requested_limit or offset != requested_offset:
        raise ValueError("Oracle Cloud search envelope limit or offset did not match the request.")
    observed_site = envelope.get("SiteNumber")
    if not isinstance(observed_site, str) or observed_site != site_number:
        raise ValueError("Oracle Cloud search envelope site number did not match the source.")
    requisitions = envelope.get("requisitionList")
    if not isinstance(requisitions, list):
        raise ValueError("Oracle Cloud search envelope requires a requisitionList array.")
    if len(requisitions) > requested_limit:
        raise ValueError("Oracle Cloud returned more jobs than the requested page limit.")
    return requisitions, total


def _detail_item(payload: object) -> Mapping[object, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("Oracle Cloud detail root must be an object.")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
        raise ValueError("Oracle Cloud detail response requires exactly one job.")
    return items[0]


def _normalize_listing(
    source: CompanySource,
    parameters: Mapping[str, str],
    raw: object,
) -> NormalizedJob:
    if not isinstance(raw, Mapping):
        raise ValueError("Oracle Cloud requisition must be an object.")
    external_id = _required_string(raw, "Id")
    title = _required_string(raw, "Title")
    locations = _listing_locations(raw)
    location_missing = not locations
    if not locations:
        locations = ["Location unavailable"]
    posted_raw = _optional_string(raw.get("PostedDate"))
    posted_date = _parse_date(posted_raw)
    site_number = quote(parameters["site_number"], safe="")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.ORACLE_CLOUD.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=" | ".join(_unique_strings(locations)),
        location_normalized=_shared_locations(locations),
        published_at=posted_date,
        published_at_raw=posted_raw,
        date_basis=DateBasis.PUBLISHED if posted_date is not None else DateBasis.UNKNOWN,
        canonical_url=(
            f"https://{parameters['host']}/hcmUI/CandidateExperience/en/sites/"
            f"{site_number}/job/{quote(external_id, safe='')}"
        ),
        source_metadata={
            "detail_available": True,
            "listing_location_missing": location_missing,
            "primary_location_country": raw.get("PrimaryLocationCountry"),
            "short_description": _plain_text_optional(raw.get("ShortDescriptionStr")),
            "workplace_type": raw.get("WorkplaceType"),
            "workplace_type_code": raw.get("WorkplaceTypeCode"),
        },
    )


def _listing_locations(raw: Mapping[object, object]) -> list[str]:
    locations: list[str] = []
    primary = _optional_string(raw.get("PrimaryLocation"))
    if primary is not None:
        locations.append(primary)
    for field in ("secondaryLocations", "otherWorkLocations", "workLocation"):
        children = raw.get(field)
        if children is None:
            continue
        if not isinstance(children, list) or any(
            not isinstance(item, Mapping) for item in children
        ):
            raise ValueError(f"Oracle Cloud {field} must be an array of objects.")
        for item in children:
            if not isinstance(item, Mapping):
                continue
            name = _optional_string(item.get("Name")) or _optional_string(item.get("LocationName"))
            if name is not None:
                locations.append(name)
    return _unique_strings(locations)


def _description(detail: Mapping[object, object]) -> str | None:
    parts = _unique_strings(
        text
        for field in (
            "ExternalDescriptionStr",
            "ExternalResponsibilitiesStr",
            "ExternalQualificationsStr",
            "ShortDescriptionStr",
        )
        if (text := _plain_text_optional(detail.get(field))) is not None
    )
    return "\n\n".join(parts) if parts else None


def _raw_id(raw: object) -> str:
    if isinstance(raw, Mapping):
        value = raw.get("Id")
        if isinstance(value, str):
            return value
    return "<missing>"


def _required_string(raw: Mapping[object, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Oracle Cloud requisition field {key} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"Oracle Cloud {field} must be a non-negative integer.")
    return value


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


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


def _plain_text_optional(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _VisibleTextParser()
    parser.feed(html.unescape(value))
    parser.close()
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text or None


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
