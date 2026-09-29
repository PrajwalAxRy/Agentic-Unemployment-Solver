"""Deterministic custom adapter for Amazon Jobs' public India inventory."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
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

AMAZON_JOBS_ADAPTER_KEY = "amazon_jobs_india"
AMAZON_JOBS_CAREERS_URL = "https://www.amazon.jobs/en/search?country=IND&sort=recent"
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100

_EXTERNAL_ID_PATTERN = re.compile(r"[A-Za-z0-9]+")
_JOB_PATH_PATTERN = re.compile(r"/en/jobs/([A-Za-z0-9]+)/[a-z0-9][a-z0-9_-]*")
_POSTED_DATE_PATTERN = re.compile(r"([A-Z][a-z]+)\s+([0-9]{1,2}),\s+([0-9]{4})")
_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
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


class AmazonJobsAdapter:
    """Retrieve Amazon's count-checked public India collection with full descriptions."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = AMAZON_JOBS_ADAPTER_KEY

    def __init__(
        self,
        client: BoundedHttpClient | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if page_size <= 0 or page_size > 100 or max_pages <= 0:
            raise ValueError("page_size must be 1-100 and max_pages must be positive")
        self._client = client or BoundedHttpClient()
        self._page_size = page_size
        self._max_pages = max_pages

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None
        raw_count = 0
        parse_error_count = 0

        for page_index in range(self._max_pages):
            offset = page_index * self._page_size
            try:
                response = self._client.get(
                    _listing_endpoint(offset, self._page_size),
                    accepted_content_types=("application/json",),
                    referer=AMAZON_JOBS_CAREERS_URL,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    page_index,
                    diagnostics,
                )
            if not _is_expected_response_url(response.final_url):
                diagnostics.append(
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "Amazon Jobs search redirected outside the approved JSON route.",
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
                payload = json.loads(response.body)
                root = _required_mapping(payload, "Amazon Jobs search response")
                response_error = root.get("error")
                if response_error not in (None, ""):
                    raise ValueError("Amazon Jobs search response reported an error.")
                total = root.get("hits")
                rows = root.get("jobs")
                if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                    raise ValueError("Amazon Jobs hits must be a non-negative integer.")
                if not isinstance(rows, list):
                    raise ValueError("Amazon Jobs jobs must be an array.")
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
                        "Amazon Jobs total changed during offset pagination.",
                        page_index=page_index,
                        expected_total=expected_total,
                        observed_total=total,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)
            if len(rows) > self._page_size:
                diagnostics.append(
                    _diagnostic(
                        "page_size_exceeded",
                        DiagnosticSeverity.ERROR,
                        "Amazon Jobs returned more rows than requested.",
                        page_index=page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)
            if not rows and total > raw_count:
                diagnostics.append(
                    _diagnostic(
                        "unexpected_empty_page",
                        DiagnosticSeverity.ERROR,
                        "Amazon Jobs returned an empty page before its declared total.",
                        page_index=page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)

            for job_index, row in enumerate(rows):
                try:
                    job = _normalize_job(source, row)
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
                if external_id in seen_ids:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "Amazon Jobs returned a duplicate iCIMS job ID.",
                            page_index=page_index,
                            job_index=job_index,
                        )
                    )
                    return _result(
                        source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics
                    )
                if external_id is not None:
                    seen_ids.add(external_id)
                jobs.append(job)
            raw_count += len(rows)

            if raw_count > total:
                diagnostics.append(
                    _diagnostic(
                        "declared_count_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Amazon Jobs returned more rows than its declared total.",
                        declared_total=total,
                        parsed_rows=raw_count,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)
            if raw_count == total:
                if parse_error_count:
                    return _result(
                        source,
                        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                        jobs,
                        page_index + 1,
                        diagnostics,
                    )
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    complete=True,
                )
            if len(rows) < self._page_size:
                diagnostics.append(
                    _diagnostic(
                        "incomplete_pagination",
                        DiagnosticSeverity.ERROR,
                        "Amazon Jobs returned a short page before its declared total.",
                        page_index=page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_index + 1, diagnostics)

        diagnostics.append(
            _diagnostic(
                "pagination_limit",
                DiagnosticSeverity.ERROR,
                "Amazon Jobs pagination exceeded the configured page limit.",
                max_pages=self._max_pages,
                expected_total=expected_total if expected_total is not None else "unknown",
            )
        )
        return _result(source, AdapterOutcome.SUSPICIOUS, jobs, self._max_pages, diagnostics)


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _BLOCK_TAGS or tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != AMAZON_JOBS_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Amazon Jobs adapter requires adapter_key={AMAZON_JOBS_ADAPTER_KEY}."
        )
    if source.careers_url != AMAZON_JOBS_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Amazon Jobs adapter requires careers_url={AMAZON_JOBS_CAREERS_URL}."
        )


def _listing_endpoint(offset: int, page_size: int) -> str:
    query = urlencode(
        (
            ("base_query", ""),
            ("country", "IND"),
            ("offset", offset),
            ("result_limit", page_size),
            ("sort", "recent"),
        )
    )
    return f"https://www.amazon.jobs/en/search.json?{query}"


def _is_expected_response_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.amazon.jobs"
        and parsed.path == "/en/search.json"
    )


def _normalize_job(source: CompanySource, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "Amazon Jobs job")
    external_id = _required_string(raw, "id_icims", "Amazon Jobs job")
    if not _EXTERNAL_ID_PATTERN.fullmatch(external_id):
        raise ValueError("Amazon Jobs id_icims must contain only letters and digits.")
    if raw.get("country_code") != "IND":
        raise ValueError("Amazon Jobs India collection contained a non-India job.")
    title = _required_string(raw, "title", "Amazon Jobs job")
    job_path = _required_string(raw, "job_path", "Amazon Jobs job")
    canonical_url = _canonical_job_url(urljoin("https://www.amazon.jobs", job_path))
    _validate_job_url(canonical_url, external_id)
    location = _location_text(raw)
    posted_raw = _required_string(raw, "posted_date", "Amazon Jobs job")
    published_at = _posted_date(posted_raw)
    description = _description(raw)
    business_category = _optional_string(raw.get("business_category"))
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=published_at,
        published_at_raw=posted_raw,
        date_basis=DateBasis.PUBLISHED,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": AMAZON_JOBS_ADAPTER_KEY,
            "internal_id": raw.get("id"),
            "business_category": business_category,
            "aws_owned": business_category == "aws",
            "company_name": raw.get("company_name"),
            "job_category": raw.get("job_category"),
            "job_family": raw.get("job_family"),
            "job_schedule_type": raw.get("job_schedule_type"),
            "source_system": raw.get("source_system"),
            "application_url": raw.get("url_next_step"),
        },
    )


def _location_text(raw: Mapping[object, object]) -> str:
    location_parts: list[str] = []
    locations = raw.get("locations")
    if locations is not None and not isinstance(locations, list):
        raise ValueError("Amazon Jobs locations must be an array when present.")
    for value in locations or []:
        if not isinstance(value, str):
            raise ValueError("Amazon Jobs location entries must be JSON strings.")
        try:
            location = _required_mapping(json.loads(value), "Amazon Jobs location")
        except json.JSONDecodeError as error:
            raise ValueError("Amazon Jobs location entry was not valid JSON.") from error
        normalized = _optional_string(location.get("normalizedLocation"))
        if normalized is not None:
            location_parts.append(normalized)
        work_type = _optional_string(location.get("type"))
        if work_type is not None:
            location_parts.append(work_type.replace("_", " ").title())
    if not location_parts:
        location_parts.append(_required_string(raw, "normalized_location", "Amazon Jobs job"))
    return " | ".join(_unique_strings(location_parts))


def _description(raw: Mapping[object, object]) -> str:
    sections: list[str] = []
    for label, field, required in (
        ("Description", "description", True),
        ("Basic qualifications", "basic_qualifications", False),
        ("Preferred qualifications", "preferred_qualifications", False),
    ):
        value = _optional_string(raw.get(field))
        if value is None:
            if required:
                raise ValueError(f"Amazon Jobs job field {field} must be a non-empty string.")
            continue
        text = _plain_text(html.unescape(value))
        if text:
            sections.extend((label, text))
        elif required:
            raise ValueError("Amazon Jobs job description normalized to empty text.")
    return "\n\n".join(sections)


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _posted_date(value: str) -> date:
    match = _POSTED_DATE_PATTERN.fullmatch(value)
    if match is None or match.group(1) not in _MONTHS:
        raise ValueError("Amazon Jobs posted_date must use 'Month D, YYYY'.")
    try:
        return date(int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2)))
    except ValueError as error:
        raise ValueError("Amazon Jobs posted_date was invalid.") from error


def _validate_job_url(url: str, external_id: str) -> None:
    parsed = urlsplit(url)
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.amazon.jobs"
        or match is None
        or match.group(1) != external_id
    ):
        raise ValueError("Amazon Jobs job path must match its iCIMS ID.")


def _canonical_job_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


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


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _required_string(raw: Mapping[object, object], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} field {key} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


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
    **context: int | str,
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
