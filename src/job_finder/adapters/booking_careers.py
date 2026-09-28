"""Deterministic adapter for Booking.com's public Jibe careers inventory."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit, urlunsplit

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

BOOKING_ADAPTER_KEY = "booking_jibe_inventory"
BOOKING_CAREERS_URL = "https://jobs.booking.com/booking/jobs"
_API_PREFIX = "https://jobs.booking.com/api/jobs"
_COMPANY_FILTER = "Booking.com%20Company%20Hierarchy%7CTransport%20Company%20Hierarchy"
_PAGE_SIZE = 10
_MAX_PAGES = 100
_ID_PATTERN = re.compile(r"[0-9]+")
_JOB_PATH_PATTERN = re.compile(r"/booking/jobs/([0-9]+)")
_BLOCK_TAGS = {
    "article",
    "br",
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
    "section",
    "ul",
}


class BookingCareersAdapter:
    """Retrieve every public Booking.com job from its bounded Jibe API."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = BOOKING_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None
        expected_pages: int | None = None

        for page in range(1, _MAX_PAGES + 1):
            page_url = _page_url(page)
            try:
                response = self._client.get(
                    page_url,
                    accepted_content_types=("application/json",),
                    referer=BOOKING_CAREERS_URL,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    _request_outcome(error),
                    jobs,
                    page - 1,
                    diagnostics,
                )
            if response.final_url != page_url:
                return _failed(
                    source,
                    jobs,
                    page,
                    diagnostics,
                    "unexpected_redirect",
                    "Booking.com jobs API redirected outside the requested page.",
                )
            try:
                payload = json.loads(response.body)
                root = _required_mapping(payload, "Booking.com response")
                raw_jobs = _required_list(root.get("jobs"), "Booking.com jobs")
                total = _non_negative_int(root.get("totalCount"), "Booking.com totalCount")
                count = _non_negative_int(root.get("count"), "Booking.com count")
                if count != total:
                    raise ValueError("Booking.com count must equal totalCount.")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                return _failed(
                    source,
                    jobs,
                    page,
                    diagnostics,
                    "unsupported_schema",
                    str(error),
                )

            if expected_total is None:
                expected_total = total
                expected_pages = max(1, math.ceil(total / _PAGE_SIZE))
                if expected_pages > _MAX_PAGES:
                    return _failed(
                        source,
                        jobs,
                        page,
                        diagnostics,
                        "page_limit_exceeded",
                        "Booking.com inventory exceeded the configured page limit.",
                    )
            elif total != expected_total:
                return _suspicious(
                    source,
                    jobs,
                    page,
                    diagnostics,
                    "total_changed",
                    "Booking.com totalCount changed during pagination.",
                )

            if expected_pages is None or expected_total is None:
                raise AssertionError("Booking.com pagination was not initialized")
            expected_rows = (
                0
                if expected_total == 0
                else min(_PAGE_SIZE, expected_total - ((page - 1) * _PAGE_SIZE))
            )
            if len(raw_jobs) != expected_rows:
                return _suspicious(
                    source,
                    jobs,
                    page,
                    diagnostics,
                    "incomplete_page",
                    "Booking.com page length did not match the declared total.",
                )

            for index, raw_job in enumerate(raw_jobs):
                try:
                    job = _normalize_job(source, raw_job)
                except ValueError as error:
                    diagnostics.append(
                        _diagnostic(
                            "malformed_job",
                            DiagnosticSeverity.ERROR,
                            str(error),
                            page=page,
                            job_index=index,
                        )
                    )
                    return _result(
                        source,
                        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                        jobs,
                        page,
                        diagnostics,
                    )
                external_id = job.external_job_id
                if external_id is None:
                    raise AssertionError("Booking.com jobs require an external ID")
                if external_id in seen_ids:
                    return _suspicious(
                        source,
                        jobs,
                        page,
                        diagnostics,
                        "duplicate_job_id",
                        "Booking.com returned a duplicate requisition ID.",
                    )
                seen_ids.add(external_id)
                jobs.append(job)

            if page == expected_pages:
                if len(jobs) != expected_total:
                    return _suspicious(
                        source,
                        jobs,
                        page,
                        diagnostics,
                        "incomplete_collection",
                        "Booking.com normalized job count did not match totalCount.",
                    )
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page,
                    diagnostics,
                    complete=True,
                )

        return _failed(
            source,
            jobs,
            _MAX_PAGES,
            diagnostics,
            "page_limit_exceeded",
            "Booking.com inventory exceeded the configured page limit.",
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != BOOKING_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Booking.com adapter requires adapter_key={BOOKING_ADAPTER_KEY}."
        )
    if source.careers_url != BOOKING_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Booking.com adapter requires careers_url={BOOKING_CAREERS_URL}."
        )


def _page_url(page: int) -> str:
    return (
        f"{_API_PREFIX}?page={page}&sortBy=relevance&descending=false&internal=false"
        f"&tags1={_COMPANY_FILTER}"
    )


def _normalize_job(source: CompanySource, value: object) -> NormalizedJob:
    wrapper = _required_mapping(value, "Booking.com job wrapper")
    raw = _required_mapping(wrapper.get("data"), "Booking.com job data")
    external_id = _required_string(raw, "req_id", "Booking.com job")
    slug = _required_string(raw, "slug", "Booking.com job")
    if _ID_PATTERN.fullmatch(external_id) is None or slug != external_id:
        raise ValueError("Booking.com req_id and slug must be matching numeric identifiers.")
    if _required_string(raw, "client_code", "Booking.com job") != "workingatbooking":
        raise ValueError("Booking.com job client_code did not identify the official board.")
    if raw.get("internal") is not False or raw.get("searchable") is not True:
        raise ValueError("Booking.com job must be external-searchable and not internal.")

    title = _required_string(raw, "title", "Booking.com job")
    location = _required_string(raw, "full_location", "Booking.com job")
    description = _plain_text(_required_string(raw, "description", "Booking.com job"))
    if not description:
        raise ValueError("Booking.com job description normalized to empty text.")
    canonical_url = _canonical_job_url(
        _required_string(
            _required_mapping(raw.get("meta_data"), "Booking.com job meta_data"),
            "canonical_url",
            "Booking.com job meta_data",
        ),
        external_id,
    )
    published_raw = _required_string(raw, "posted_date", "Booking.com job")
    published_at = _timestamp(published_raw, "Booking.com posted_date")
    apply_url = _required_string(raw, "apply_url", "Booking.com job")
    _validate_apply_url(apply_url, external_id)
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
        published_at_raw=published_raw,
        date_basis=DateBasis.PUBLISHED,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": BOOKING_ADAPTER_KEY,
            "apply_url": apply_url,
            "department": _optional_string(raw.get("department")),
            "category": tuple(_string_list(raw.get("category"), "Booking.com category")),
            "employment_type": _optional_string(raw.get("employment_type")),
        },
    )


def _canonical_job_url(value: str, external_id: str) -> str:
    parsed = urlsplit(value)
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path.rstrip("/"))
    query = parse_qs(parsed.query)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "jobs.booking.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or match is None
        or match.group(1) != external_id
        or query != {"lang": ["en-us"]}
    ):
        raise ValueError("Booking.com canonical URL did not match its requisition ID.")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""))


def _validate_apply_url(value: str, external_id: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "external-workingatbooking.icims.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != f"/jobs/{external_id}/login"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Booking.com apply URL did not match its requisition ID.")


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(html.unescape(value))
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed


def _normalized_locations(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _normalize_text(piece) for piece in re.split(r"[,|;/]", value) if piece.strip()
        )
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _required_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    return value


def _required_string(raw: Mapping[object, object], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} field {key} must be a non-empty string.")
    return re.sub(r"\s+", " ", value).strip()


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return re.sub(r"\s+", " ", value).strip()
    return None


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain only non-empty strings.")
        normalized = re.sub(r"\s+", " ", item).strip()
        if normalized not in result:
            result.append(normalized)
    return result


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer.")
    return value


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


def _failed(
    source: CompanySource,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    category: str,
    message: str,
) -> AdapterResult:
    diagnostics.append(_diagnostic(category, DiagnosticSeverity.ERROR, message))
    return _result(
        source,
        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
        jobs,
        page_count,
        diagnostics,
    )


def _suspicious(
    source: CompanySource,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    category: str,
    message: str,
) -> AdapterResult:
    diagnostics.append(_diagnostic(category, DiagnosticSeverity.ERROR, message))
    return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)


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
