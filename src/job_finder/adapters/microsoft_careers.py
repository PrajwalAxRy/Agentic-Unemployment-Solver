"""Deterministic adapter for Microsoft's public India careers API."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpRequestError,
    HttpResponse,
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

MICROSOFT_CAREERS_ADAPTER_KEY = "microsoft_careers_india"
MICROSOFT_CAREERS_URL = "https://apply.careers.microsoft.com/careers?location=India&hl=en"
DEFAULT_PAGE_SIZE = 10
DEFAULT_MAX_PAGES = 100
DEFAULT_REQUEST_INTERVAL_SECONDS = 7.0
DEFAULT_MAX_REQUESTS_PER_WINDOW = 20
DEFAULT_REQUEST_WINDOW_SECONDS = 300.0
MAX_SINGLE_WAIT_SECONDS = 30.0

_HOST = "apply.careers.microsoft.com"
_SEARCH_PATH = "/api/pcsx/search"
_DETAIL_API_PATH = "/api/pcsx/position_details"
_JOB_PATH_PATTERN = re.compile(r"/careers/job/([0-9]+)/?")
_EXTERNAL_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "tr",
    "ul",
}


class MicrosoftCareersAdapter:
    """Retrieve Microsoft's count-checked India inventory and deferred details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = MICROSOFT_CAREERS_ADAPTER_KEY

    def __init__(
        self,
        client: BoundedHttpClient | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
        request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
        max_requests_per_window: int = DEFAULT_MAX_REQUESTS_PER_WINDOW,
        request_window_seconds: float = DEFAULT_REQUEST_WINDOW_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if page_size <= 0 or max_pages <= 0:
            raise ValueError("page_size and max_pages must be positive")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds cannot be negative")
        if max_requests_per_window <= 0 or request_window_seconds <= 0:
            raise ValueError("rolling request budget values must be positive")
        self._client = client or BoundedHttpClient()
        self._page_size = page_size
        self._max_pages = max_pages
        self._request_interval_seconds = request_interval_seconds
        self._max_requests_per_window = max_requests_per_window
        self._request_window_seconds = request_window_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_started: float | None = None
        self._request_starts: deque[float] = deque()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_external_ids: set[str] = set()
        seen_position_ids: set[str] = set()
        expected_total: int | None = None

        for page_index in range(self._max_pages):
            start = page_index * self._page_size
            url = _search_url(start)
            try:
                response = self._get(url)
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    page_index,
                    diagnostics,
                )
            if not _is_search_response(response.final_url, start):
                diagnostics.append(
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "Microsoft careers search redirected outside the approved API route.",
                        page_index=page_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_index + 1,
                    diagnostics,
                )
            try:
                data = _api_data(response.body, "Microsoft careers search")
                total = _required_nonnegative_int(data, "count", "Microsoft careers search data")
                rows = data.get("positions")
                if not isinstance(rows, list):
                    raise ValueError("Microsoft careers search positions must be an array.")
                sort_by = _required_string(data, "sortBy", "Microsoft careers search data")
                if sort_by != "relevance":
                    raise ValueError(
                        "Microsoft careers search did not honor the required relevance sort."
                    )
            except _RemoteApiError as error:
                diagnostics.append(
                    _diagnostic(
                        "remote_api_error",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        page_index=page_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_index + 1,
                    diagnostics,
                )
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
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
                    page_index + 1,
                    diagnostics,
                )

            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                diagnostics.append(
                    _diagnostic(
                        "changing_total",
                        DiagnosticSeverity.ERROR,
                        "Microsoft careers total changed during offset pagination.",
                        page_index=page_index,
                        expected_total=expected_total,
                        observed_total=total,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)

            remaining = expected_total - len(jobs)
            expected_page_count = min(self._page_size, max(remaining, 0))
            if len(rows) != expected_page_count:
                diagnostics.append(
                    _diagnostic(
                        "declared_count_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Microsoft careers page size does not reconcile with its declared total.",
                        page_index=page_index,
                        expected_page_count=expected_page_count,
                        observed_page_count=len(rows),
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)

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
                            page_index=page_index,
                            job_index=job_index,
                        )
                    )
                    continue
                position_id = job.source_metadata.get("position_id")
                if job.external_job_id in seen_external_ids or position_id in seen_position_ids:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "Microsoft careers returned a duplicate ATS or position ID.",
                            page_index=page_index,
                            job_index=job_index,
                        )
                    )
                    return _result(
                        source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics
                    )
                if job.external_job_id is not None:
                    seen_external_ids.add(job.external_job_id)
                if isinstance(position_id, str):
                    seen_position_ids.add(position_id)
                jobs.append(job)
            if parse_errors:
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_index + 1,
                    diagnostics,
                )

            if len(jobs) == expected_total:
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    complete=True,
                )

        diagnostics.append(
            _diagnostic(
                "pagination_limit",
                DiagnosticSeverity.ERROR,
                "Microsoft careers pagination exceeded the configured page limit.",
                max_pages=self._max_pages,
                expected_total=expected_total if expected_total is not None else "unknown",
            )
        )
        return _result(source, AdapterOutcome.SUSPICIOUS, jobs, self._max_pages, diagnostics)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one Microsoft detail payload and cross-check listing identity."""
        _validate_source(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Microsoft detail job does not match the configured source.")
        position_id = job.source_metadata.get("position_id")
        if not isinstance(position_id, str) or not position_id.isdigit():
            raise ValueError("Microsoft detail retrieval requires a numeric position ID.")
        canonical_url, canonical_position_id = _canonical_job_url(job.canonical_url)
        if canonical_url != job.canonical_url or canonical_position_id != position_id:
            raise ValueError("Microsoft detail URL identity does not match the listing.")

        detail_url = _detail_url(position_id)
        response = self._get(detail_url)
        if not _is_detail_response(response.final_url, position_id):
            raise ValueError("Microsoft detail response redirected outside the approved API route.")
        try:
            data = _api_data(response.body, "Microsoft careers detail")
        except _RemoteApiError as error:
            raise ValueError(str(error)) from error
        detail_position_id = str(
            _required_nonnegative_int(data, "id", "Microsoft careers detail data")
        )
        if detail_position_id != position_id:
            raise ValueError("Microsoft detail position ID does not match the listing.")
        external_id = _required_string(data, "atsJobId", "Microsoft careers detail data")
        if external_id != job.external_job_id:
            raise ValueError("Microsoft detail ATS job ID does not match the listing.")
        title = _required_string(data, "name", "Microsoft careers detail data")
        if _normalize_text(title) != job.title_normalized:
            raise ValueError("Microsoft detail title does not match the listing.")
        public_url = _required_string(data, "publicUrl", "Microsoft careers detail data")
        detail_canonical_url, public_position_id = _canonical_job_url(public_url)
        if detail_canonical_url != job.canonical_url or public_position_id != position_id:
            raise ValueError("Microsoft detail public URL does not match the listing.")
        timestamp = _posted_timestamp(data.get("postedTs"))
        if timestamp != job.published_at:
            raise ValueError("Microsoft detail publication timestamp does not match the listing.")
        description_html = _required_string(data, "jobDescription", "Microsoft careers detail data")
        description = _plain_text(description_html)
        if not description:
            raise ValueError("Microsoft detail description normalized to empty text.")
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "employment_type": _optional_string(data.get("efcustomTextEmploymentType")),
                "required_travel": _optional_string(data.get("efcustomTextRequiredTravel")),
                "role_type": _optional_string(data.get("efcustomTextRoletype")),
                "work_site": _optional_string(data.get("efcustomTextWorkSite")),
            }
        )
        return replace(
            job,
            title_original=title,
            title_normalized=_normalize_text(title),
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=metadata,
        )

    def _get(self, url: str) -> HttpResponse:
        self._respect_request_limits()
        return self._client.get(
            url,
            accepted_content_types=("application/json",),
            referer=MICROSOFT_CAREERS_URL,
        )

    def _respect_request_limits(self) -> None:
        while True:
            now = self._monotonic()
            if self._last_request_started is not None:
                spacing_wait = self._request_interval_seconds - (now - self._last_request_started)
                if spacing_wait > 0:
                    self._sleep(min(spacing_wait, MAX_SINGLE_WAIT_SECONDS))
                    continue
            while (
                self._request_starts
                and now - self._request_starts[0] >= self._request_window_seconds
            ):
                self._request_starts.popleft()
            if len(self._request_starts) < self._max_requests_per_window:
                self._request_starts.append(now)
                self._last_request_started = now
                return
            window_wait = self._request_window_seconds - (now - self._request_starts[0])
            self._sleep(min(max(window_wait, 0.0), MAX_SINGLE_WAIT_SECONDS))


class _RemoteApiError(ValueError):
    """The public API returned a structured error envelope."""


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "template"}:
            self._ignored_depth += 1
        if not self._ignored_depth and (tag in _BLOCK_TAGS or tag == "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._ignored_depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag in {"script", "style", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != MICROSOFT_CAREERS_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Microsoft careers adapter requires adapter_key={MICROSOFT_CAREERS_ADAPTER_KEY}."
        )
    if source.careers_url != MICROSOFT_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Microsoft careers adapter requires careers_url={MICROSOFT_CAREERS_URL}."
        )


def _search_url(start: int) -> str:
    query = urlencode(
        (
            ("domain", "microsoft.com"),
            ("query", ""),
            ("location", "India"),
            ("start", start),
            ("sort_by", "relevance"),
            ("hl", "en"),
        )
    )
    return f"https://{_HOST}{_SEARCH_PATH}?{query}"


def _detail_url(position_id: str) -> str:
    query = urlencode((("position_id", position_id), ("domain", "microsoft.com"), ("hl", "en")))
    return f"https://{_HOST}{_DETAIL_API_PATH}?{query}"


def _is_search_response(url: str, start: int) -> bool:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    return (
        _is_api_origin(parsed)
        and parsed.path == _SEARCH_PATH
        and query
        == {
            "domain": ["microsoft.com"],
            "query": [""],
            "location": ["India"],
            "start": [str(start)],
            "sort_by": ["relevance"],
            "hl": ["en"],
        }
    )


def _is_detail_response(url: str, position_id: str) -> bool:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    return (
        _is_api_origin(parsed)
        and parsed.path == _DETAIL_API_PATH
        and query
        == {
            "position_id": [position_id],
            "domain": ["microsoft.com"],
            "hl": ["en"],
        }
    )


def _is_api_origin(parsed: object) -> bool:
    return (
        getattr(parsed, "scheme", None) == "https"
        and getattr(parsed, "hostname", None) == _HOST
        and getattr(parsed, "port", None) is None
        and getattr(parsed, "username", None) is None
        and getattr(parsed, "password", None) is None
        and not getattr(parsed, "fragment", None)
    )


def _api_data(body: bytes, context: str) -> Mapping[object, object]:
    root = _required_mapping(json.loads(body), context)
    status = root.get("status")
    error = _required_mapping(root.get("error"), f"{context} error")
    message = _optional_string(error.get("message"))
    error_body = _optional_string(error.get("body"))
    if status != 200 or message is not None or error_body is not None:
        raise _RemoteApiError(f"{context} returned a structured remote error.")
    return _required_mapping(root.get("data"), f"{context} data")


def _normalize_listing(source: CompanySource, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "Microsoft careers position")
    position_id = str(_required_nonnegative_int(raw, "id", "Microsoft careers position"))
    external_id = _required_string(raw, "atsJobId", "Microsoft careers position")
    if not _EXTERNAL_ID_PATTERN.fullmatch(external_id):
        raise ValueError("Microsoft careers atsJobId contains unsupported characters.")
    display_job_id = _required_string(raw, "displayJobId", "Microsoft careers position")
    title = _required_string(raw, "name", "Microsoft careers position")
    position_url = _required_string(raw, "positionUrl", "Microsoft careers position")
    canonical_url, url_position_id = _canonical_job_url(urljoin(f"https://{_HOST}", position_url))
    if url_position_id != position_id:
        raise ValueError("Microsoft careers position URL does not match its ID.")
    locations = _string_array(raw.get("locations"), "Microsoft careers locations")
    if not locations:
        raise ValueError("Microsoft careers position must contain a location.")
    standardized_locations = _string_array(
        raw.get("standardizedLocations"), "Microsoft careers standardizedLocations"
    )
    published_at = _posted_timestamp(raw.get("postedTs"))
    location = " | ".join(_unique_strings(locations))
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=_normalize_text(title),
        location_original=location,
        location_normalized=_normalized_locations(location),
        published_at=published_at,
        published_at_raw=str(raw.get("postedTs")),
        date_basis=DateBasis.PUBLISHED,
        canonical_url=canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": MICROSOFT_CAREERS_ADAPTER_KEY,
            "position_id": position_id,
            "display_job_id": display_job_id,
            "department": _optional_string(raw.get("department")),
            "standardized_locations": tuple(standardized_locations),
            "work_location_option": _optional_string(raw.get("workLocationOption")),
            "location_flexibility": _optional_string(raw.get("locationFlexibility")),
            "india_search_result": True,
        },
    )


def _canonical_job_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
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
        raise ValueError("Microsoft job URL must be an official numeric job-detail path.")
    return f"https://{_HOST}{parsed.path.rstrip('/')}", match.group(1)


def _posted_timestamp(value: object) -> datetime:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("Microsoft careers postedTs must be a positive integer epoch.")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError("Microsoft careers postedTs is outside the supported range.") from error


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


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


def _string_array(value: object, context: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context} entries must be non-empty strings.")
        result.append(item.strip())
    return result


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalized_locations(value: str) -> tuple[str, ...]:
    return tuple(
        _unique_strings(
            _normalize_text(piece) for piece in re.split(r"[,|;/]", value) if piece.strip()
        )
    )


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
