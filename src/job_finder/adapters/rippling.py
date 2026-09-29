"""Adapter for public Rippling ATS job boards."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
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
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_title,
)

_SLUG_PATTERN = re.compile(r"[A-Za-z0-9-]+")
_UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_JOB_PATH_PATTERN = re.compile(rf"/([A-Za-z0-9-]+)/jobs/({_UUID_PATTERN})/?")
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
    "p",
    "pre",
    "section",
    "table",
    "td",
    "tr",
    "ul",
}


class RipplingAdapter:
    """Read a complete embedded Rippling collection and public job details."""

    adapter_type = AdapterType.RIPPLING

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
        document = _decode_html(response.body, source, diagnostics)
        if document is None:
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
        if not _is_expected_response_url(response.final_url, slug, listing=True):
            diagnostics.append(
                diagnostic(
                    "unexpected_redirect",
                    DiagnosticSeverity.ERROR,
                    "Rippling listing redirected outside the configured public board.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)

        try:
            page_props = _page_props(document)
            _validate_board(page_props, slug)
            collection = _listing_collection(page_props, slug)
        except ValueError as error:
            diagnostics.append(
                diagnostic("unsupported_schema", DiagnosticSeverity.ERROR, str(error))
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)

        items = collection.get("items")
        page = collection.get("page")
        page_size = collection.get("pageSize")
        total_items = collection.get("totalItems")
        total_pages = collection.get("totalPages")
        if (
            not isinstance(items, list)
            or not isinstance(page, int)
            or isinstance(page, bool)
            or not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or not isinstance(total_items, int)
            or isinstance(total_items, bool)
            or not isinstance(total_pages, int)
            or isinstance(total_pages, bool)
            or page != 0
            or page_size <= 0
            or total_items < 0
            or total_pages < 0
        ):
            diagnostics.append(
                diagnostic(
                    "invalid_collection_metadata",
                    DiagnosticSeverity.ERROR,
                    "Rippling listing metadata was missing or internally invalid.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)
        if total_pages > 1:
            diagnostics.append(
                diagnostic(
                    "unverified_pagination",
                    DiagnosticSeverity.ERROR,
                    "Rippling board requires pagination that has not been verified "
                    "for this adapter.",
                    total_pages=total_pages,
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, [], diagnostics)
        if total_items != len(items) or total_pages != (1 if total_items else 0):
            diagnostics.append(
                diagnostic(
                    "declared_count_mismatch",
                    DiagnosticSeverity.ERROR,
                    "Rippling's declared collection size did not match embedded jobs.",
                    total_items=total_items,
                    parsed_items=len(items),
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, [], diagnostics)
        if not items:
            return _result(source, AdapterOutcome.EMPTY, [], diagnostics, complete=True)

        jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()
        parse_error_count = 0
        for job_index, item in enumerate(items):
            try:
                job = _normalize_listing(source, slug, item)
            except ValueError as error:
                parse_error_count += 1
                diagnostics.append(
                    diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=job_index,
                    )
                )
                continue
            external_id = job.external_job_id
            if external_id in seen_ids:
                diagnostics.append(
                    diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Rippling returned a duplicate job ID.",
                        job_index=job_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, diagnostics)
            if external_id is not None:
                seen_ids.add(external_id)
            jobs.append(job)
        if parse_error_count:
            return _result(
                source,
                AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                jobs,
                diagnostics,
            )
        diagnostics.append(
            diagnostic(
                "uncertain_creation_date_requires_detail",
                DiagnosticSeverity.WARNING,
                "Rippling detail createdOn is retained as uncertain date evidence.",
                count=len(jobs),
            )
        )
        return _result(source, AdapterOutcome.SUCCESS, jobs, diagnostics, complete=True)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve a public Rippling job detail without changing listing identity."""
        slug = _board_slug(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Rippling detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("Rippling detail retrieval requires an external job ID.")
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
        if not _is_expected_response_url(
            response.final_url,
            slug,
            listing=False,
            external_id=job.external_job_id,
        ):
            raise ValueError("Rippling detail response URL does not match the listing.")
        page_props = _page_props(document)
        _validate_board(page_props, slug)
        api_data = _required_mapping(page_props.get("apiData"), "Rippling apiData")
        posting = _required_mapping(api_data.get("jobPost"), "Rippling jobPost")
        detail_id = _required_string(posting, "uuid", "Rippling detail")
        if detail_id != job.external_job_id:
            raise ValueError("Rippling detail UUID does not match the listing.")
        detail_url = _required_string(posting, "url", "Rippling detail")
        _validate_job_url(detail_url, slug, detail_id)
        title = _required_string(posting, "name", "Rippling detail")
        descriptions = _required_mapping(posting.get("description"), "Rippling description")
        description_parts = [
            _plain_text(html.unescape(value))
            for value in descriptions.values()
            if isinstance(value, str) and value.strip()
        ]
        description = "\n\n".join(part for part in description_parts if part) or None
        created_raw = _optional_string(posting.get("createdOn"))
        created_at = _parse_timestamp(created_raw)
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "createdOn": created_raw,
                "employment_type": posting.get("employmentType"),
                "unlisted_from_search": posting.get("unlistedFromSearch"),
                "detail_description_missing": description is None,
            }
        )
        return replace(
            job,
            title_original=title,
            title_normalized=normalize_title(title),
            published_at=created_at,
            published_at_raw=created_raw,
            date_basis=DateBasis.UNKNOWN,
            description=description,
            description_hash=(
                hashlib.sha256(description.encode("utf-8")).hexdigest()
                if description is not None
                else None
            ),
            source_metadata=metadata,
        )


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


def _board_slug(source: CompanySource) -> str:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.RIPPLING,
        required_parameters=("board_slug",),
    )
    slug = parameters["board_slug"].strip()
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Rippling board_slug must contain only letters, digits, and hyphens.")
    expected = _listing_endpoint(slug)
    if (source.careers_url or "").rstrip("/") != expected:
        raise ValueError("Rippling board_slug must match the configured careers URL.")
    return slug


def _listing_endpoint(slug: str) -> str:
    return f"https://ats.rippling.com/{slug}/jobs"


def _normalize_listing(source: CompanySource, slug: str, item: object) -> NormalizedJob:
    raw = _required_mapping(item, "Rippling listing job")
    external_id = _required_string(raw, "id", "Rippling listing")
    title = _required_string(raw, "name", "Rippling listing")
    canonical_url = _required_string(raw, "url", "Rippling listing")
    _validate_job_url(canonical_url, slug, external_id)
    locations_raw = raw.get("locations")
    if not isinstance(locations_raw, list) or not locations_raw:
        raise ValueError("Rippling listing locations must be a non-empty array.")
    location_parts: list[str] = []
    workplace_types: list[str] = []
    for location in locations_raw:
        location_mapping = _required_mapping(location, "Rippling listing location")
        location_parts.append(_required_string(location_mapping, "name", "Rippling location"))
        country = _optional_string(location_mapping.get("country"))
        if country is not None:
            location_parts.append(country)
        workplace = _optional_string(location_mapping.get("workplaceType"))
        if workplace is not None:
            workplace_types.append(workplace.replace("_", " ").title())
    location_parts.extend(workplace_types)
    location = " | ".join(unique_strings(location_parts))
    department = raw.get("department")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.RIPPLING.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=_canonical_job_url(canonical_url),
        description=None,
        description_hash=None,
        source_metadata={
            "department": department.get("name") if isinstance(department, Mapping) else None,
            "language": raw.get("language"),
            "workplace_types": tuple(workplace_types),
        },
    )


def _page_props(document: str) -> Mapping[object, object]:
    parser = _NextDataParser()
    parser.feed(document)
    parser.close()
    if len(parser.documents) != 1:
        raise ValueError("Rippling page requires exactly one __NEXT_DATA__ document.")
    root = _required_mapping(parser.documents[0], "Rippling __NEXT_DATA__")
    props = _required_mapping(root.get("props"), "Rippling props")
    return _required_mapping(props.get("pageProps"), "Rippling pageProps")


def _validate_board(page_props: Mapping[object, object], slug: str) -> None:
    api_data = _required_mapping(page_props.get("apiData"), "Rippling apiData")
    board = _required_mapping(api_data.get("jobBoard"), "Rippling jobBoard")
    if board.get("boardType") != "RIPPLING" or board.get("slug") != slug:
        raise ValueError("Rippling page board metadata does not match the configured slug.")


def _listing_collection(page_props: Mapping[object, object], slug: str) -> Mapping[object, object]:
    state = _required_mapping(page_props.get("dehydratedState"), "Rippling dehydratedState")
    queries = state.get("queries")
    if not isinstance(queries, list):
        raise ValueError("Rippling dehydratedState queries must be an array.")
    matches: list[Mapping[object, object]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            continue
        key = query.get("queryKey")
        if not isinstance(key, list) or len(key) < 3 or key[:3] != ["board", slug, "job-posts"]:
            continue
        query_state = _required_mapping(query.get("state"), "Rippling query state")
        matches.append(_required_mapping(query_state.get("data"), "Rippling query data"))
    if len(matches) != 1:
        raise ValueError("Rippling page requires one matching job-posts collection.")
    return matches[0]


def _canonical_job_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _validate_job_url(url: str, slug: str, external_id: str) -> None:
    parsed = urlsplit(urljoin(_listing_endpoint(slug), url))
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "ats.rippling.com"
        or match is None
        or match.group(1) != slug
        or match.group(2).casefold() != external_id.casefold()
    ):
        raise ValueError("Rippling job URL must match the configured board slug and job ID.")


def _is_expected_response_url(
    url: str,
    slug: str,
    *,
    listing: bool,
    external_id: str | None = None,
) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "ats.rippling.com":
        return False
    if listing:
        return parsed.path.rstrip("/") == f"/{slug}/jobs"
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    return (
        match is not None
        and match.group(1) == slug
        and (external_id is None or match.group(2).casefold() == external_id.casefold())
    )


def _decode_html(
    body: bytes,
    source: CompanySource,
    diagnostics: list[AdapterDiagnostic],
) -> str | None:
    del source
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        diagnostics.append(
            diagnostic(
                "invalid_html",
                DiagnosticSeverity.ERROR,
                "Rippling response was not valid UTF-8 HTML.",
            )
        )
        return None


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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
