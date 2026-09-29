"""Deterministic adapter for Apple's server-rendered public India jobs site."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.errors import DetailContentMissing, DetailIdentityMismatch
from job_finder.adapters.http_client import BoundedHttpClient, HttpFailureCategory, HttpRequestError
from job_finder.core.access_detection import is_access_block_html
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

APPLE_JOBS_ADAPTER_KEY = "apple_jobs_india"
APPLE_JOBS_CAREERS_URL = "https://jobs.apple.com/en-us/search?location=india-INDC"
DEFAULT_PAGE_SIZE = 20
DEFAULT_MAX_PAGES = 100

_HOST = "jobs.apple.com"
_SEARCH_PATH = "/en-us/search"
_HYDRATION_MARKER = "window.__staticRouterHydrationData = JSON.parse("
_DETAIL_PATH_PATTERN = re.compile(r"/en-us/details/([0-9]+(?:-[0-9]+)?)/([a-z0-9][a-z0-9-]*)/?")
_PIPE_EXTERNAL_ID_PATTERN = re.compile(r"PIPE-([0-9]+)")
_REQUISITION_EXTERNAL_ID_PATTERN = re.compile(r"([0-9]+)-([0-9]+)")


class AppleJobsAdapter:
    """Retrieve Apple's exact-count India inventory and deferred details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = APPLE_JOBS_ADAPTER_KEY

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
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()
        expected_total: int | None = None

        for page_number in range(1, self._max_pages + 1):
            page_url = _listing_url(page_number)
            try:
                response = self._client.get(
                    page_url,
                    accepted_content_types=("text/html",),
                    referer=APPLE_JOBS_CAREERS_URL,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    page_number - 1,
                    diagnostics,
                )
            if not _is_listing_url(response.final_url, page_number):
                diagnostics.append(
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "Apple jobs redirected outside the approved India search page.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_number,
                    diagnostics,
                )
            try:
                document = response.body.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(
                    _diagnostic(
                        "invalid_encoding",
                        DiagnosticSeverity.ERROR,
                        "Apple jobs listing was not valid UTF-8.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_number,
                    diagnostics,
                )
            if is_access_block_html(document):
                diagnostics.append(
                    request_failure_diagnostic(
                        HttpRequestError(
                            HttpFailureCategory.ACCESS_BLOCK,
                            "access-control or login page detected",
                            status_code=response.status_code,
                        )
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.BLOCKED,
                    jobs,
                    page_number,
                    diagnostics,
                )
            try:
                search = _loader_value(document, "search")
                total = _required_nonnegative_int(search, "totalRecords", "Apple search data")
                observed_page = _required_nonnegative_int(search, "page", "Apple search data")
                if observed_page != page_number:
                    raise ValueError("Apple search hydration page does not match the request.")
                request_url = _required_string(search, "requestUrl", "Apple search data")
                if not _is_listing_url(request_url, page_number):
                    raise ValueError(
                        "Apple search hydration requestUrl does not match the request."
                    )
                rows = search.get("searchResults")
                if not isinstance(rows, list):
                    raise ValueError("Apple searchResults must be an array.")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
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
                    page_number,
                    diagnostics,
                )

            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                diagnostics.append(
                    _diagnostic(
                        "changing_total",
                        DiagnosticSeverity.ERROR,
                        "Apple jobs total changed during pagination.",
                        page_number=page_number,
                        expected_total=expected_total,
                        observed_total=total,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_number, diagnostics)

            expected_page_count = min(self._page_size, max(expected_total - len(jobs), 0))
            if len(rows) != expected_page_count:
                diagnostics.append(
                    _diagnostic(
                        "declared_count_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Apple jobs page size does not reconcile with its declared total.",
                        page_number=page_number,
                        expected_page_count=expected_page_count,
                        observed_page_count=len(rows),
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_number, diagnostics)

            parse_errors = 0
            for job_index, row in enumerate(rows):
                try:
                    job = _normalize_listing(source, row)
                except ValueError as error:
                    parse_errors += 1
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
                if job.external_job_id in seen_ids or job.canonical_url in seen_urls:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "Apple jobs returned a duplicate external ID or detail URL.",
                            page_number=page_number,
                            job_index=job_index,
                        )
                    )
                    return _result(
                        source, AdapterOutcome.SUSPICIOUS, jobs, page_number, diagnostics
                    )
                if job.external_job_id is not None:
                    seen_ids.add(job.external_job_id)
                seen_urls.add(job.canonical_url)
                jobs.append(job)
            if parse_errors:
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_number,
                    diagnostics,
                )

            if len(jobs) == expected_total:
                unknown_count = sum(job.date_basis is DateBasis.UNKNOWN for job in jobs)
                if unknown_count:
                    diagnostics.append(
                        _diagnostic(
                            "unstable_pipeline_dates",
                            DiagnosticSeverity.WARNING,
                            "Apple managed-pipeline timestamps are unstable and remain unknown.",
                            count=unknown_count,
                        )
                    )
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page_number,
                    diagnostics,
                    complete=True,
                )

        diagnostics.append(
            _diagnostic(
                "pagination_limit",
                DiagnosticSeverity.ERROR,
                "Apple jobs pagination exceeded the configured page limit.",
                max_pages=self._max_pages,
                expected_total=expected_total if expected_total is not None else "unknown",
            )
        )
        return _result(source, AdapterOutcome.SUSPICIOUS, jobs, self._max_pages, diagnostics)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one Apple detail hydration payload and cross-check listing identity."""
        _validate_source(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise DetailIdentityMismatch("Apple detail job does not match the configured source.")
        if job.external_job_id is None:
            raise DetailContentMissing("Apple detail retrieval requires an external job ID.")
        canonical_url, detail_identifier = _canonical_detail_url(job.canonical_url)
        if canonical_url != job.canonical_url:
            raise DetailIdentityMismatch("Apple detail URL is not canonical.")

        response = self._client.get(
            job.canonical_url,
            accepted_content_types=("text/html",),
            referer=APPLE_JOBS_CAREERS_URL,
        )
        document = response.body.decode("utf-8")
        if is_access_block_html(document):
            raise HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
        response_url, response_identifier = _canonical_detail_url(response.final_url)
        if response_url != job.canonical_url or response_identifier != detail_identifier:
            raise DetailIdentityMismatch("Apple detail response URL does not match the listing.")

        detail = _loader_value(document, "jobDetails")
        request_url = _required_string(detail, "requestUrl", "Apple detail data")
        request_canonical, request_identifier = _canonical_detail_url(request_url)
        if request_canonical != job.canonical_url or request_identifier != detail_identifier:
            raise DetailIdentityMismatch(
                "Apple detail hydration requestUrl does not match the listing."
            )
        canonical_links = _canonical_links(detail.get("metaLinks"))
        if canonical_links != {job.canonical_url}:
            raise DetailIdentityMismatch(
                "Apple detail hydration must expose exactly one matching canonical URL."
            )
        data = _required_mapping(detail.get("jobsData"), "Apple jobsData")
        position_id = _required_string(data, "positionId", "Apple jobsData")
        if position_id != job.source_metadata.get("position_id"):
            raise DetailIdentityMismatch("Apple detail position ID does not match the listing.")
        if not detail_identifier.startswith(position_id):
            raise DetailIdentityMismatch(
                "Apple detail URL identifier does not match its position ID."
            )
        managed_pipeline = job.source_metadata.get("managed_pipeline_role") is True
        if managed_pipeline:
            detail_internal_id = _required_string(data, "id", "Apple jobsData")
            if detail_internal_id != job.external_job_id:
                raise DetailIdentityMismatch("Apple pipeline detail ID does not match the listing.")
        else:
            job_number = _required_string(data, "jobNumber", "Apple jobsData")
            if job_number != job.external_job_id:
                raise DetailIdentityMismatch("Apple detail jobNumber does not match the listing.")
        title = _required_string(data, "postingTitle", "Apple jobsData")
        if normalize_title(title) != job.title_normalized:
            raise DetailIdentityMismatch("Apple detail title does not match the listing.")
        slug = _required_string(data, "transformedPostingTitle", "Apple jobsData")
        if not job.canonical_url.endswith(f"/{slug}"):
            raise DetailIdentityMismatch("Apple detail title slug does not match the listing URL.")
        if job.date_basis is DateBasis.PUBLISHED:
            detail_date = _published_datetime(
                _required_string(data, "postDateInGMT", "Apple jobsData")
            )
            if detail_date != job.published_at:
                raise DetailIdentityMismatch(
                    "Apple detail publication timestamp does not match the listing."
                )
        locations = _location_text(data.get("locations"))
        description = _detail_description(data)
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "detail_internal_id": _optional_string(data.get("id")),
                "employment_type": _optional_string(data.get("employmentType")),
                "job_type": _optional_string(data.get("jobType")),
                "team_names": tuple(_optional_string_array(data.get("teamNames"))),
            }
        )
        return replace(
            job,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=locations,
            location_normalized=_shared_locations(locations),
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=metadata,
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != APPLE_JOBS_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Apple jobs adapter requires adapter_key={APPLE_JOBS_ADAPTER_KEY}."
        )
    if source.careers_url != APPLE_JOBS_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Apple jobs adapter requires careers_url={APPLE_JOBS_CAREERS_URL}."
        )


def _listing_url(page_number: int) -> str:
    return (
        APPLE_JOBS_CAREERS_URL
        if page_number == 1
        else f"{APPLE_JOBS_CAREERS_URL}&page={page_number}"
    )


def _is_listing_url(url: str, page_number: int) -> bool:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    observed_page = query.get("page", ["1"])
    return (
        parsed.scheme == "https"
        and parsed.hostname == _HOST
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == _SEARCH_PATH
        and query.get("location") == ["india-INDC"]
        and observed_page == [str(page_number)]
        and set(query) <= {"location", "page"}
        and not parsed.fragment
    )


def _loader_value(document: str, key: str) -> Mapping[object, object]:
    marker_index = document.find(_HYDRATION_MARKER)
    if marker_index < 0:
        raise ValueError("Apple page omitted the static router hydration marker.")
    argument = document[marker_index + len(_HYDRATION_MARKER) :].lstrip()
    encoded, end = json.JSONDecoder().raw_decode(argument)
    if not isinstance(encoded, str):
        raise ValueError("Apple hydration JSON.parse argument must be a JSON string.")
    if not argument[end:].lstrip().startswith(")"):
        raise ValueError("Apple hydration JSON.parse call was not terminated.")
    root = _required_mapping(json.loads(encoded), "Apple hydration root")
    loader_data = _required_mapping(root.get("loaderData"), "Apple loaderData")
    return _required_mapping(loader_data.get(key), f"Apple loaderData {key}")


def _normalize_listing(source: CompanySource, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "Apple search result")
    external_id = _required_string(raw, "id", "Apple search result")
    req_id = _required_string(raw, "reqId", "Apple search result")
    job_position_id = _required_string(raw, "jobPositionId", "Apple search result")
    if req_id != external_id:
        raise ValueError("Apple search result id and reqId disagree.")
    position_id = _required_string(raw, "positionId", "Apple search result")
    job_type = _required_string(raw, "type", "Apple search result")
    managed_pipeline = raw.get("managedPipelineRole")
    if not isinstance(managed_pipeline, bool):
        raise ValueError("Apple managedPipelineRole must be boolean.")
    if job_type not in {"PIPE", "REQ"}:
        raise ValueError("Apple role type must be PIPE or REQ.")
    pipeline_match = _PIPE_EXTERNAL_ID_PATTERN.fullmatch(external_id)
    requisition_match = _REQUISITION_EXTERNAL_ID_PATTERN.fullmatch(external_id)
    if managed_pipeline:
        if pipeline_match is None or pipeline_match.group(1) != position_id:
            raise ValueError("Apple managed-pipeline ID must match its positionId.")
        if job_type != "PIPE" or job_position_id != external_id:
            raise ValueError("Apple managed-pipeline identity fields disagree.")
    else:
        if requisition_match is None or requisition_match.group(1) != position_id:
            raise ValueError("Apple requisition job number must match its positionId.")
        if job_position_id not in {f"REQ-{position_id}", f"PIPE-{position_id}"}:
            raise ValueError("Apple requisition jobPositionId is inconsistent.")
    title = _required_string(raw, "postingTitle", "Apple search result")
    slug = _required_string(raw, "transformedPostingTitle", "Apple search result")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise ValueError("Apple transformedPostingTitle must be a lowercase URL slug.")
    locations = _listing_locations(raw.get("locations"))
    detail_identifier = position_id if managed_pipeline else external_id
    canonical_url = f"https://{_HOST}/en-us/details/{detail_identifier}/{slug}"
    published_raw = _required_string(raw, "postDateInGMT", "Apple search result")
    published_at = None if managed_pipeline else _published_datetime(published_raw)
    date_basis = DateBasis.UNKNOWN if managed_pipeline else DateBasis.PUBLISHED
    team = _required_mapping(raw.get("team"), "Apple search result team")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=locations,
        location_normalized=_shared_locations(locations),
        published_at=published_at,
        published_at_raw=published_raw,
        date_basis=date_basis,
        canonical_url=canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": APPLE_JOBS_ADAPTER_KEY,
            "position_id": position_id,
            "managed_pipeline_role": managed_pipeline,
            "job_position_id": job_position_id,
            "posting_date_display": _optional_string(raw.get("postingDate")),
            "team_name": _optional_string(team.get("teamName")),
            "team_code": _optional_string(team.get("teamCode")),
            "home_office": raw.get("homeOffice"),
            "multi_location": raw.get("isMultiLocation"),
        },
    )


def _listing_locations(value: object) -> str:
    rows = _mapping_array(value, "Apple listing locations")
    locations: list[str] = []
    india_seen = False
    for row in rows:
        country = _required_string(row, "countryName", "Apple listing location")
        india_seen = india_seen or country.casefold() == "india"
        city = _optional_string(row.get("city"))
        state = _optional_string(row.get("stateProvince"))
        name = _optional_string(row.get("name"))
        locality = city or (name if name and name.casefold() != country.casefold() else None)
        pieces = [piece for piece in (locality, state, country) if piece]
        locations.append(", ".join(pieces))
    if not locations or not india_seen:
        raise ValueError("Apple India search result must contain an India location.")
    return " | ".join(_unique_strings(locations))


def _location_text(value: object) -> str:
    rows = _mapping_array(value, "Apple detail locations")
    locations: list[str] = []
    for row in rows:
        country = _required_string(row, "countryName", "Apple detail location")
        city = _optional_string(row.get("city"))
        state = _optional_string(row.get("stateProvince"))
        name = _optional_string(row.get("name"))
        pieces = [piece for piece in (city, state, country) if piece]
        locations.append(", ".join(pieces) if city or state else name or country)
    if not locations:
        raise ValueError("Apple detail must contain a location.")
    return " | ".join(_unique_strings(locations))


def _canonical_detail_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    match = _DETAIL_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("Apple job URL must be an official en-us detail path.")
    return f"https://{_HOST}{parsed.path.rstrip('/')}", match.group(1)


def _canonical_links(value: object) -> set[str]:
    rows = _mapping_array(value, "Apple detail metaLinks")
    links: set[str] = set()
    for row in rows:
        if row.get("rel") != "canonical":
            continue
        href = _required_string(row, "href", "Apple canonical link")
        canonical, _ = _canonical_detail_url(href)
        links.add(canonical)
    return links


def _published_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Apple postDateInGMT must be an ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError("Apple postDateInGMT must include a timezone.")
    return parsed


def _detail_description(data: Mapping[object, object]) -> str:
    sections: list[str] = []
    for label, field in (
        ("Summary", "jobSummary"),
        ("Description", "description"),
        ("Responsibilities", "responsibilities"),
        ("Minimum qualifications", "minimumQualifications"),
        ("Preferred qualifications", "preferredQualifications"),
    ):
        value = _optional_string(data.get(field))
        if value is None:
            continue
        text = _clean_text(value)
        if text:
            sections.append(f"{label}\n\n{text}")
    description = "\n\n".join(sections)
    if not description:
        raise ValueError("Apple detail description fields must not all be empty.")
    return description


def _clean_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _mapping_array(value: object, context: str) -> list[Mapping[object, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    return [_required_mapping(item, f"{context} entry") for item in value]


def _required_string(raw: Mapping[object, object], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} field {key} must be a non-empty string.")
    return value.strip()


def _required_nonnegative_int(raw: Mapping[object, object], key: str, context: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} field {key} must be a non-negative integer.")
    return value


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_string_array(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Apple optional string array must be an array.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Apple optional string array entries must be non-empty strings.")
        result.append(item.strip())
    return result


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
