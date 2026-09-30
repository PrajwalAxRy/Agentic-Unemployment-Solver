"""Adapter for public Recruiterflow job boards."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from job_finder.adapters._support import diagnostic, request_outcome, unique_strings
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
from job_finder.core.validation import clean_optional, required_string
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_title,
)

_SLUG_PATTERN = re.compile(r"[A-Za-z0-9-]+")
_ASSIGNMENT_PATTERN = re.compile(r"window\.jobsList\s*=\s*")
_JOB_PATH_PATTERN = re.compile(r"/([A-Za-z0-9-]+)/jobs/([1-9][0-9]*)/?")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
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


class RecruiterflowAdapter:
    """Read Recruiterflow's complete server-rendered collection and JSON-LD details."""

    adapter_type = AdapterType.RECRUITERFLOW

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        slug = _board_slug(source)
        diagnostics: list[AdapterDiagnostic] = []
        try:
            response = self._client.get(
                _listing_endpoint(slug),
                accepted_content_types=("text/html",),
                referer=source.careers_url,
            )
        except HttpRequestError as error:
            diagnostics.append(request_failure_diagnostic(error))
            return _result(source, request_outcome(error), [], diagnostics)
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError:
            diagnostics.append(
                diagnostic(
                    "invalid_html",
                    DiagnosticSeverity.ERROR,
                    "Recruiterflow response was not valid UTF-8 HTML.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)
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
            return _result(source, AdapterOutcome.BLOCKED, [], diagnostics)
        if not _is_expected_url(response.final_url, slug, listing=True):
            diagnostics.append(
                diagnostic(
                    "unexpected_redirect",
                    DiagnosticSeverity.ERROR,
                    "Recruiterflow listing redirected outside the configured public board.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)

        try:
            collection = _jobs_collection(document)
            department_rows, department_ids = _collection_view(
                collection, "department", include_rows=True
            )
            _, group_ids = _collection_view(collection, "group", include_rows=False)
            _, location_ids = _collection_view(collection, "location", include_rows=False)
        except ValueError as error:
            diagnostics.append(
                diagnostic("unsupported_schema", DiagnosticSeverity.ERROR, str(error))
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)

        if department_ids != group_ids or department_ids != location_ids:
            diagnostics.append(
                diagnostic(
                    "inconsistent_collection_views",
                    DiagnosticSeverity.ERROR,
                    "Recruiterflow's department, group, and location views disagree.",
                    department_jobs=len(department_ids),
                    group_jobs=len(group_ids),
                    location_jobs=len(location_ids),
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, [], diagnostics)
        if not department_rows:
            return _result(source, AdapterOutcome.EMPTY, [], diagnostics, complete=True)

        jobs: list[NormalizedJob] = []
        for job_index, (department, item) in enumerate(department_rows):
            try:
                jobs.append(_normalize_listing(source, slug, department, item))
            except ValueError as error:
                diagnostics.append(
                    diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=job_index,
                    )
                )
        if len(jobs) != len(department_rows):
            return _result(
                source,
                AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                jobs,
                diagnostics,
            )
        return _result(source, AdapterOutcome.SUCCESS, jobs, diagnostics, complete=True)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one public JSON-LD JobPosting without changing listing identity."""
        slug = _board_slug(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Recruiterflow detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("Recruiterflow detail retrieval requires an external job ID.")
        _validate_job_url(job.canonical_url, slug, job.external_job_id)
        response = self._client.get(
            job.canonical_url,
            accepted_content_types=("text/html",),
            referer=source.careers_url,
        )
        document = response.body.decode("utf-8")
        if is_access_block_html(document):
            raise HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
        if not _is_expected_url(
            response.final_url, slug, listing=False, external_id=job.external_job_id
        ):
            raise ValueError("Recruiterflow detail response URL does not match the listing.")
        posting = _job_posting(document, job.external_job_id)
        title = required_string(posting, "title", "Recruiterflow JobPosting")
        description_html = required_string(posting, "description", "Recruiterflow JobPosting")
        description = _plain_text(html.unescape(description_html))
        if not description:
            raise ValueError("Recruiterflow JobPosting description was empty.")
        published_raw = required_string(posting, "datePosted", "Recruiterflow JobPosting")
        published_at = _publication_date(published_raw)
        location = _posting_location(posting) or job.location_original
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "employment_type": posting.get("employmentType"),
                "direct_apply": posting.get("directApply"),
            }
        )
        return replace(
            job,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=location,
            location_normalized=_shared_locations(location),
            published_at=published_at,
            published_at_raw=published_raw,
            date_basis=DateBasis.PUBLISHED,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=metadata,
        )


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[Mapping[str, str | None], str]] = []
        self._attrs: Mapping[str, str | None] | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._attrs = dict(attrs)
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._attrs is not None:
            self.scripts.append((self._attrs, "".join(self._parts)))
            self._attrs = None
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._attrs is not None:
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


def _board_slug(source: CompanySource) -> str:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.RECRUITERFLOW,
        required_parameters=("board_slug",),
    )
    slug = parameters["board_slug"].strip()
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Recruiterflow board_slug must contain only letters, digits, and hyphens.")
    if (source.careers_url or "").rstrip("/") != _listing_endpoint(slug):
        raise ValueError("Recruiterflow board_slug must match the configured careers URL.")
    return slug


def _listing_endpoint(slug: str) -> str:
    return f"https://recruiterflow.com/{slug}/jobs"


def _jobs_collection(document: str) -> Mapping[object, object]:
    parser = _ScriptParser()
    parser.feed(document)
    parser.close()
    matches: list[object] = []
    decoder = json.JSONDecoder()
    for _, script in parser.scripts:
        for marker in _ASSIGNMENT_PATTERN.finditer(script):
            try:
                value, end = decoder.raw_decode(script, marker.end())
            except json.JSONDecodeError as error:
                raise ValueError("Recruiterflow jobsList was not valid JSON.") from error
            if not script[end:].lstrip().startswith(";"):
                raise ValueError("Recruiterflow jobsList assignment was not terminated.")
            matches.append(value)
    if len(matches) != 1:
        raise ValueError("Recruiterflow page requires exactly one jobsList assignment.")
    return _required_mapping(matches[0], "Recruiterflow jobsList")


def _collection_view(
    collection: Mapping[object, object],
    key: str,
    *,
    include_rows: bool,
) -> tuple[list[tuple[str, object]], set[str]]:
    groups = collection.get(key)
    if not isinstance(groups, list):
        raise ValueError(f"Recruiterflow jobsList.{key} must be an array.")
    rows: list[tuple[str, object]] = []
    identifiers: set[str] = set()
    for group_index, group in enumerate(groups):
        if not isinstance(group, list) or len(group) != 2:
            raise ValueError(f"Recruiterflow {key} group {group_index} was malformed.")
        label = group[0]
        items = group[1]
        if not isinstance(label, str) or not label.strip() or not isinstance(items, list):
            raise ValueError(f"Recruiterflow {key} group {group_index} was malformed.")
        for item in items:
            raw = _required_mapping(item, f"Recruiterflow {key} job")
            identifier = _job_identifier(raw.get("job_id"), f"Recruiterflow {key} job")
            if identifier in identifiers:
                raise ValueError(f"Recruiterflow {key} view repeated job ID {identifier}.")
            identifiers.add(identifier)
            if include_rows:
                rows.append((label.strip(), item))
    return rows, identifiers


def _normalize_listing(
    source: CompanySource, slug: str, department: str, value: object
) -> NormalizedJob:
    raw = _required_mapping(value, "Recruiterflow listing job")
    external_id = _job_identifier(raw.get("job_id"), "Recruiterflow listing job")
    title = required_string(raw, "job_name", "Recruiterflow listing job")
    apply_link = required_string(raw, "apply_link", "Recruiterflow listing job")
    canonical_url = urljoin("https://recruiterflow.com/", apply_link)
    _validate_job_url(canonical_url, slug, external_id)
    details = required_string(raw, "details", "Recruiterflow listing job")
    remote_type = clean_optional(raw.get("remote_type"))
    location = " | ".join(unique_strings([details, remote_type or ""]))
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.RECRUITERFLOW.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=_canonical_url(canonical_url),
        description=None,
        description_hash=None,
        source_metadata={
            "department": department,
            "employment_type": raw.get("employment_type"),
            "remote_type": remote_type,
            "last_opened": raw.get("last_opened"),
        },
    )


def _job_posting(document: str, external_id: str) -> Mapping[object, object]:
    parser = _ScriptParser()
    parser.feed(document)
    parser.close()
    candidates: list[Mapping[object, object]] = []
    for attrs, script in parser.scripts:
        if attrs.get("type") != "application/ld+json" or not script.strip():
            continue
        try:
            value = json.loads(script)
        except json.JSONDecodeError:
            continue
        candidates.extend(_job_posting_candidates(value))
    matching: list[Mapping[object, object]] = []
    for candidate in candidates:
        identifier = candidate.get("identifier")
        if not isinstance(identifier, Mapping):
            continue
        value = identifier.get("value")
        if isinstance(value, str) and value.endswith(f"__{external_id}"):
            matching.append(candidate)
    if len(matching) != 1:
        raise ValueError("Recruiterflow detail requires one matching JobPosting document.")
    return matching[0]


def _job_posting_candidates(value: object) -> list[Mapping[object, object]]:
    if isinstance(value, list):
        result: list[Mapping[object, object]] = []
        for item in value:
            result.extend(_job_posting_candidates(item))
        return result
    if not isinstance(value, Mapping):
        return []
    result = [value] if value.get("@type") == "JobPosting" else []
    graph = value.get("@graph")
    if isinstance(graph, list):
        result.extend(_job_posting_candidates(graph))
    return result


def _posting_location(posting: Mapping[object, object]) -> str | None:
    raw_locations = posting.get("jobLocation")
    locations = raw_locations if isinstance(raw_locations, list) else [raw_locations]
    parts: list[str] = []
    for location in locations:
        if not isinstance(location, Mapping):
            continue
        address = location.get("address")
        if not isinstance(address, Mapping):
            continue
        for key in ("addressLocality", "addressRegion", "addressCountry"):
            value = clean_optional(address.get(key))
            if value is not None:
                parts.append(value)
    unique = unique_strings(parts)
    return " | ".join(unique) if unique else None


def _publication_date(value: str) -> date:
    if not _DATE_PATTERN.fullmatch(value):
        raise ValueError("Recruiterflow JobPosting datePosted must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Recruiterflow JobPosting datePosted was invalid.") from error


def _validate_job_url(url: str, slug: str, external_id: str) -> None:
    parsed = urlsplit(url)
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "recruiterflow.com"
        or match is None
        or match.group(1) != slug
        or match.group(2) != external_id
    ):
        raise ValueError("Recruiterflow job URL must match the configured board and job ID.")


def _is_expected_url(
    url: str,
    slug: str,
    *,
    listing: bool,
    external_id: str | None = None,
) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "recruiterflow.com":
        return False
    if listing:
        return parsed.path.rstrip("/") == f"/{slug}/jobs"
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    return (
        match is not None
        and match.group(1) == slug
        and (external_id is None or match.group(2) == external_id)
    )


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _job_identifier(value: object, context: str) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{context} job_id must be a positive integer.")
    return str(value)


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _result(
    source: CompanySource,
    outcome: AdapterOutcome,
    jobs: list[NormalizedJob],
    diagnostics: list[AdapterDiagnostic],
    *,
    complete: bool = False,
) -> AdapterResult:
    return AdapterResult(
        schema_version=1,
        source=source,
        outcome=outcome,
        jobs=tuple(jobs),
        page_count=1,
        complete=complete,
        diagnostics=tuple(diagnostics),
    )
