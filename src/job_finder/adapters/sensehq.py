"""Adapter for public SenseHQ career portals."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

from job_finder.adapters.base import request_failure_diagnostic, require_source_configuration
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

DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100
_SUBDOMAIN_PATTERN = re.compile(r"[A-Za-z0-9-]+")
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


class SenseHqAdapter:
    """Retrieve complete count-checked job collections from SenseHQ portals."""

    adapter_type = AdapterType.SENSEHQ

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
        subdomain = _career_subdomain(source)
        diagnostics: list[AdapterDiagnostic] = []
        jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None
        parse_error_count = 0
        missing_description_count = 0
        page_count = 0

        for page_index in range(self._max_pages):
            endpoint = _listing_endpoint(subdomain, page_index, self._page_size)
            try:
                response = self._client.get(
                    endpoint,
                    accepted_content_types=("text/html",),
                    referer=source.careers_url,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                outcome = AdapterOutcome.PARTIAL if jobs else _request_outcome(error)
                return _result(source, outcome, jobs, page_count, diagnostics)
            page_count += 1
            try:
                document = response.body.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(
                    _diagnostic(
                        "invalid_html",
                        DiagnosticSeverity.ERROR,
                        "SenseHQ response was not valid UTF-8 HTML.",
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
                    page_count,
                    diagnostics,
                )
            if not _is_expected_response_url(response.final_url, subdomain):
                diagnostics.append(
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "SenseHQ listing redirected outside the configured public portal.",
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
            try:
                page_props = _page_props(document)
                _validate_organization(page_props, subdomain)
                jobs_data = _required_mapping(page_props.get("jobsData"), "SenseHQ jobsData")
                rows = jobs_data.get("rows")
                total = jobs_data.get("count")
                if not isinstance(rows, list):
                    raise ValueError("SenseHQ jobsData.rows must be an array.")
                if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                    raise ValueError("SenseHQ jobsData.count must be a non-negative integer.")
            except ValueError as error:
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
                        "changing_total",
                        DiagnosticSeverity.ERROR,
                        "SenseHQ job total changed during pagination.",
                        page_index=page_index,
                        expected_total=expected_total,
                        observed_total=total,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            if not rows and total > len(jobs):
                diagnostics.append(
                    _diagnostic(
                        "unexpected_empty_page",
                        DiagnosticSeverity.ERROR,
                        "SenseHQ returned an empty page before the declared total was reached.",
                        page_index=page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)

            for row_index, row in enumerate(rows):
                try:
                    job = _normalize_job(source, subdomain, row)
                except ValueError as error:
                    parse_error_count += 1
                    diagnostics.append(
                        _diagnostic(
                            "malformed_job",
                            DiagnosticSeverity.ERROR,
                            str(error),
                            page_index=page_index,
                            row_index=row_index,
                        )
                    )
                    continue
                external_id = job.external_job_id
                if external_id in seen_ids:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "SenseHQ returned a duplicate job ID across pages.",
                            page_index=page_index,
                            row_index=row_index,
                        )
                    )
                    return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
                if external_id is not None:
                    seen_ids.add(external_id)
                if job.description is None:
                    missing_description_count += 1
                jobs.append(job)

            if len(jobs) + parse_error_count >= total:
                if len(jobs) + parse_error_count != total:
                    diagnostics.append(
                        _diagnostic(
                            "declared_count_mismatch",
                            DiagnosticSeverity.ERROR,
                            "SenseHQ parsed more rows than its declared total.",
                            declared_total=total,
                            parsed_rows=len(jobs) + parse_error_count,
                        )
                    )
                    return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
                if parse_error_count:
                    return _result(
                        source,
                        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                        jobs,
                        page_count,
                        diagnostics,
                    )
                if not jobs:
                    return _result(
                        source,
                        AdapterOutcome.EMPTY,
                        [],
                        page_count,
                        diagnostics,
                        complete=True,
                    )
                diagnostics.append(
                    _diagnostic(
                        "uncertain_creation_dates",
                        DiagnosticSeverity.WARNING,
                        "SenseHQ created_on values are retained as uncertain date evidence.",
                        count=len(jobs),
                    )
                )
                if missing_description_count:
                    diagnostics.append(
                        _diagnostic(
                            "missing_descriptions",
                            DiagnosticSeverity.WARNING,
                            "SenseHQ jobs with empty public descriptions remain visible.",
                            count=missing_description_count,
                        )
                    )
                return _result(
                    source,
                    AdapterOutcome.SUCCESS,
                    jobs,
                    page_count,
                    diagnostics,
                    complete=True,
                )

        diagnostics.append(
            _diagnostic(
                "pagination_limit",
                DiagnosticSeverity.ERROR,
                "SenseHQ pagination exceeded the configured page limit.",
                max_pages=self._max_pages,
                expected_total=expected_total if expected_total is not None else "unknown",
                parsed_jobs=len(jobs),
            )
        )
        return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.documents: list[object] = []
        self._capture = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and attributes.get("id") == "__NEXT_DATA__":
            self._capture = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or not self._capture:
            return
        self._capture = False
        try:
            self.documents.append(json.loads("".join(self._parts)))
        except json.JSONDecodeError:
            self.documents.append(None)

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)


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


def _career_subdomain(source: CompanySource) -> str:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.SENSEHQ,
        required_parameters=("career_subdomain",),
    )
    subdomain = parameters["career_subdomain"].strip().lower()
    if not _SUBDOMAIN_PATTERN.fullmatch(subdomain):
        raise ValueError("SenseHQ career_subdomain must contain only letters, digits, and hyphens.")
    if (source.careers_url or "").rstrip("/") != f"https://{subdomain}.sensehq.com/careers":
        raise ValueError("SenseHQ career_subdomain must match the configured careers URL.")
    return subdomain


def _listing_endpoint(subdomain: str, page: int, page_size: int) -> str:
    query = urlencode({"page": page, "pageSize": page_size})
    return f"https://{subdomain}.sensehq.com/careers?{query}"


def _is_expected_response_url(url: str, subdomain: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == f"{subdomain}.sensehq.com"
        and parsed.path.rstrip("/") == "/careers"
    )


def _page_props(document: str) -> Mapping[object, object]:
    parser = _NextDataParser()
    parser.feed(document)
    parser.close()
    if len(parser.documents) != 1:
        raise ValueError("SenseHQ page requires exactly one __NEXT_DATA__ document.")
    root = _required_mapping(parser.documents[0], "SenseHQ __NEXT_DATA__")
    props = _required_mapping(root.get("props"), "SenseHQ props")
    return _required_mapping(props.get("pageProps"), "SenseHQ pageProps")


def _validate_organization(page_props: Mapping[object, object], subdomain: str) -> None:
    organization = _required_mapping(page_props.get("organization"), "SenseHQ organization")
    if (
        organization.get("career_page_subdomain") != subdomain
        or organization.get("domain") != "sensehq.com"
    ):
        raise ValueError("SenseHQ organization metadata does not match the configured portal.")


def _normalize_job(source: CompanySource, subdomain: str, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "SenseHQ job")
    job_id = raw.get("id")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError("SenseHQ job id must be a positive integer.")
    if raw.get("job_status") != "OPEN":
        raise ValueError("SenseHQ public collection contained a non-open job.")
    title = _required_string(raw, "title", "SenseHQ job")
    location_parts = [_required_string(raw, "location", "SenseHQ job")]
    office = raw.get("office")
    if isinstance(office, Mapping):
        for key in ("city", "state", "country"):
            item = _optional_string(office.get(key))
            if item is not None:
                location_parts.append(item)
    workplace = _optional_string(raw.get("workplace_type"))
    if workplace is not None:
        location_parts.append(workplace.replace("_", " ").title())
    location = " | ".join(_unique_strings(location_parts))
    created_on = _epoch_millis(raw.get("created_on"), "created_on")
    updated_on = _optional_epoch_millis(raw.get("updated_on"))
    description_html = _optional_string(raw.get("description_external"))
    description = _plain_text(html.unescape(description_html)) if description_html else None
    if not description:
        description = None
    external_id = str(job_id)
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.SENSEHQ.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=created_on,
        published_at_raw=str(raw["created_on"]),
        date_basis=DateBasis.UNKNOWN,
        canonical_url=f"https://{subdomain}.sensehq.com/careers/jobs/{external_id}",
        description=description,
        description_hash=(
            hashlib.sha256(description.encode("utf-8")).hexdigest()
            if description is not None
            else None
        ),
        source_metadata={
            "organization_id": raw.get("organization_id"),
            "department": raw.get("department"),
            "job_type": raw.get("job_type"),
            "job_code": raw.get("code"),
            "open_positions": raw.get("open_positions"),
            "experience_start": raw.get("experience_start"),
            "experience_end": raw.get("experience_end"),
            "workplace_type": workplace,
            "updated_on": updated_on.isoformat() if updated_on is not None else None,
        },
    )


def _epoch_millis(value: object, field: str) -> datetime:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"SenseHQ job {field} must be positive epoch milliseconds.")
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OSError, OverflowError, ValueError) as error:
        raise ValueError(f"SenseHQ job {field} was outside the supported range.") from error


def _optional_epoch_millis(value: object) -> datetime | None:
    if value is None:
        return None
    return _epoch_millis(value, "updated_on")


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


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
