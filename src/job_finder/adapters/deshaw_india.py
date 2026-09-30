"""Deterministic adapter for D. E. Shaw India's public careers index."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from html.parser import HTMLParser
from urllib.parse import urlsplit

from job_finder.adapters._support import diagnostic, request_outcome
from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
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
from job_finder.core.validation import clean_optional, required_string
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_title,
)

DESHAW_INDIA_ADAPTER_KEY = "deshaw_india_index"
DESHAW_INDIA_CAREERS_URL = "https://www.deshawindia.com/careers"

_HOST = "www.deshawindia.com"
_PAGE = "/careers/[[...slug]]"
_JOB_SLUG_PATTERN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*-([0-9]+)")
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


class DeshawIndiaAdapter:
    """Read the complete public regular-jobs array embedded by the India careers site."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = DESHAW_INDIA_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                DESHAW_INDIA_CAREERS_URL,
                accepted_content_types=("text/html",),
                referer=DESHAW_INDIA_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                request_outcome(error),
                [],
                0,
                [request_failure_diagnostic(error)],
            )

        if not _is_canonical_careers_url(response.final_url):
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "D. E. Shaw India careers redirected outside the approved page.",
                    )
                ],
            )
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    diagnostic(
                        "invalid_encoding",
                        DiagnosticSeverity.ERROR,
                        "D. E. Shaw India careers was not valid UTF-8.",
                    )
                ],
            )
        if is_access_block_html(document):
            block_error = HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
            return _result(
                source,
                AdapterOutcome.BLOCKED,
                [],
                1,
                [request_failure_diagnostic(block_error)],
            )

        try:
            payload = _next_data(document)
            if payload.get("page") != _PAGE:
                raise ValueError("D. E. Shaw India page identifier was unexpected.")
            props = _required_mapping(payload.get("props"), "Next.js props")
            page_props = _required_mapping(props.get("pageProps"), "Next.js pageProps")
            if page_props.get("jobsFetchingError") is not False:
                raise ValueError("D. E. Shaw India reported a jobs-fetching error.")
            regular_jobs = _required_list(page_props.get("regularJobs"), "regularJobs")
            _required_list(page_props.get("internalJobs"), "internalJobs")
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [diagnostic("unsupported_schema", DiagnosticSeverity.ERROR, str(error))],
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        for job_index, raw in enumerate(regular_jobs):
            try:
                job = _normalize_job(source, raw)
            except ValueError as error:
                diagnostics.append(
                    diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=job_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    1,
                    diagnostics,
                )
            external_id = job.external_job_id
            if external_id is None:
                raise AssertionError("D. E. Shaw India jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "D. E. Shaw India returned a duplicate public job ID.",
                        job_index=job_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, 1, diagnostics)
            seen_ids.add(external_id)
            jobs.append(job)

        if jobs:
            diagnostics.append(
                diagnostic(
                    "missing_publication_date",
                    DiagnosticSeverity.WARNING,
                    "The public D. E. Shaw India job contract exposes no publication date.",
                    count=len(jobs),
                )
            )
        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            1,
            diagnostics,
            complete=True,
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != DESHAW_INDIA_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"D. E. Shaw India adapter requires adapter_key={DESHAW_INDIA_ADAPTER_KEY}"
        )
    if source.careers_url != DESHAW_INDIA_CAREERS_URL:
        raise AdapterConfigurationError(
            f"D. E. Shaw India adapter requires careers_url={DESHAW_INDIA_CAREERS_URL}"
        )


def _normalize_job(source: CompanySource, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "regular job")
    data = _required_mapping(raw.get("data"), "regular job data")
    external_id = _positive_id(raw.get("id"), "regular job id")
    if _positive_id(data.get("id"), "regular job data id") != external_id:
        raise ValueError("D. E. Shaw India job IDs did not match.")
    title = required_string(raw, "displayName", "regular job")
    if required_string(data, "displayName", "regular job data") != title:
        raise ValueError("D. E. Shaw India job titles did not match.")
    if data.get("activeOnJobsListing") is not True:
        raise ValueError("D. E. Shaw India regular job was not active on the public listing.")

    job_slug = required_string(data, "jobUrl", "regular job data")
    slug_match = _JOB_SLUG_PATTERN.fullmatch(job_slug)
    if slug_match is None or slug_match.group(1) != external_id:
        raise ValueError("D. E. Shaw India job URL did not match its numeric ID.")
    canonical_url = f"{DESHAW_INDIA_CAREERS_URL}/{job_slug.casefold()}"

    metadata = _required_mapping(data.get("jobMetadata"), "job metadata")
    locations = _location_pairs(metadata.get("jobLocations"), "job metadata locations")
    offices = _location_pairs(raw.get("office"), "regular job offices")
    if locations != offices:
        raise ValueError("D. E. Shaw India public office and location fields did not match.")
    location = ", ".join(name for name, _ in locations)

    description_fields = _required_mapping(data.get("jobDescription"), "job description")
    description = _description(description_fields)
    if not description:
        raise ValueError("D. E. Shaw India job description normalized to empty text.")

    department = _required_mapping(data.get("department"), "job department")
    department_name = required_string(department, "name", "job department")
    categories = _named_values(data.get("jobCategory"), "job categories")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": DESHAW_INDIA_ADAPTER_KEY,
            "department": department_name,
            "categories": tuple(categories),
            "location_abbreviations": tuple(abbreviation for _, abbreviation in locations),
            "work_status": clean_optional(metadata.get("workStatus")),
            "is_exploratory": metadata.get("isExploratory") is True,
            "valid_to_date": clean_optional(data.get("validToDate")),
        },
    )


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.capturing = False
        self.parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.capturing = True
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.capturing:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self.capturing:
            self.blocks.append("".join(self.parts).strip())
            self.capturing = False
            self.parts = []


def _next_data(document: str) -> Mapping[object, object]:
    parser = _NextDataParser()
    parser.feed(document)
    parser.close()
    if len(parser.blocks) != 1:
        raise ValueError("D. E. Shaw India page must contain exactly one __NEXT_DATA__ block.")
    payload = json.loads(parser.blocks[0])
    return _required_mapping(payload, "Next.js payload")


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


def _description(raw: Mapping[object, object]) -> str:
    candidates = (
        raw.get("websiteDescription"),
        raw.get("responsibilitiesHtml") or raw.get("responsibilities"),
        raw.get("peopleWeAreLookingForHtml") or raw.get("peopleWeAreLookingForStr"),
    )
    parts: list[str] = []
    for candidate in candidates:
        value = _text_value(candidate)
        normalized = _plain_text(value) if value is not None else ""
        if normalized and normalized not in parts:
            parts.append(normalized)
    return "\n\n".join(parts)


def _text_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return "\n".join(item for item in value if item.strip())
    return None


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(html.unescape(value))
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _location_pairs(value: object, context: str) -> tuple[tuple[str, str], ...]:
    items = _required_list(value, context)
    pairs: list[tuple[str, str]] = []
    for item in items:
        raw = _required_mapping(item, f"{context} item")
        pair = (
            required_string(raw, "name", f"{context} item"),
            required_string(raw, "abbreviation", f"{context} item"),
        )
        if pair in pairs:
            raise ValueError(f"{context} contained a duplicate location.")
        pairs.append(pair)
    if not pairs:
        raise ValueError(f"{context} must contain at least one location.")
    return tuple(pairs)


def _named_values(value: object, context: str) -> list[str]:
    items = _required_list(value, context)
    return [
        required_string(_required_mapping(item, f"{context} item"), "name", context)
        for item in items
    ]


def _positive_id(value: object, field: str) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer.")
    return str(value)


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _required_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    return value


def _is_canonical_careers_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == _HOST
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/") == "/careers"
        and not parsed.query
        and not parsed.fragment
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
