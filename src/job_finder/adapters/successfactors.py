"""Adapter for public SuccessFactors Recruiting Marketing career sites."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

from job_finder.adapters._support import diagnostic, request_outcome
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

_WHITESPACE_RUN = re.compile(r"\s+")

DEFAULT_PAGE_SIZE = 25
DEFAULT_MAX_PAGES = 100
_PATH_SEGMENT = r"[A-Za-z0-9._~%()+@-]+"
_CATEGORY_PATH = re.compile(rf"/(?:{_PATH_SEGMENT}/)?go/{_PATH_SEGMENT}/[0-9]+/")
_JOB_ID_PATH = re.compile(r"/([0-9]+)/?$")
_RESULT_RANGE = re.compile(
    r"Results\s+([0-9][0-9,]*)\s*[\u2013\u2014-]\s*([0-9][0-9,]*)\s+of\s+([0-9][0-9,]*)",
    re.IGNORECASE,
)
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
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
    "p",
    "pre",
    "section",
    "table",
    "td",
    "tr",
    "ul",
}


class SuccessFactorsAdapter:
    """Retrieve complete regional inventories from public RMK category pages."""

    adapter_type = AdapterType.SUCCESSFACTORS

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
        host, category_path = _successfactors_parameters(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        expected_total: int | None = None
        raw_job_count = 0
        parse_error_count = 0
        page_count = 0
        offset = 0

        for page_index in range(self._max_pages):
            endpoint = _listing_endpoint(host, category_path, offset)
            try:
                response = self._client.get(
                    endpoint,
                    accepted_content_types=("text/html",),
                    referer=_listing_endpoint(host, category_path, 0),
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                outcome = AdapterOutcome.PARTIAL if jobs else request_outcome(error)
                return _result(source, outcome, jobs, page_count, diagnostics)

            page_count += 1
            try:
                document = response.body.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(
                    diagnostic(
                        "invalid_html",
                        DiagnosticSeverity.ERROR,
                        "SuccessFactors response was not valid UTF-8 HTML.",
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
            if urlsplit(response.final_url).hostname != host:
                diagnostics.append(
                    diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "SuccessFactors listing redirected outside the configured careers host.",
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

            parser = _ListingParser()
            parser.feed(document)
            parser.close()
            if not parser.rows and parser.no_results:
                if page_index == 0:
                    return _result(
                        source,
                        AdapterOutcome.EMPTY,
                        jobs,
                        page_count,
                        diagnostics,
                        complete=True,
                    )
                diagnostics.append(
                    diagnostic(
                        "premature_empty_page",
                        DiagnosticSeverity.ERROR,
                        "SuccessFactors returned an empty page before pagination completed.",
                        page_index=page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            try:
                page_start, page_end, total = _pagination_range(parser.pagination_labels)
            except ValueError as error:
                diagnostics.append(
                    diagnostic(
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

            if page_start != offset + 1 or page_end - page_start + 1 != len(parser.rows):
                diagnostics.append(
                    diagnostic(
                        "invalid_page_range",
                        DiagnosticSeverity.ERROR,
                        "SuccessFactors result range did not match the requested offset and rows.",
                        page_index=page_index,
                        expected_start=offset + 1,
                        observed_start=page_start,
                        observed_end=page_end,
                        observed_rows=len(parser.rows),
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            if len(parser.rows) > self._page_size:
                diagnostics.append(
                    diagnostic(
                        "page_size_exceeded",
                        DiagnosticSeverity.ERROR,
                        "SuccessFactors returned more rows than the configured page bound.",
                        page_index=page_index,
                        expected=self._page_size,
                        observed=len(parser.rows),
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                diagnostics.append(
                    diagnostic(
                        "inventory_total_changed",
                        DiagnosticSeverity.WARNING,
                        "SuccessFactors inventory total changed during pagination.",
                        page_index=page_index,
                        expected=expected_total,
                        observed=total,
                    )
                )
                expected_total = total

            page_ids: list[str] = []
            normalized_page: list[NormalizedJob] = []
            for job_index, row in enumerate(parser.rows):
                try:
                    job = _normalize_listing(source, host, row, total, page_start, page_end)
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
                            "SuccessFactors pagination returned a duplicate job ID.",
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
                    page_ids.append(job.external_job_id)
                    seen_ids.add(job.external_job_id)
                normalized_page.append(job)

            page_fingerprint = tuple(page_ids)
            if page_fingerprint and page_fingerprint in seen_pages:
                diagnostics.append(
                    diagnostic(
                        "repeated_page",
                        DiagnosticSeverity.ERROR,
                        "SuccessFactors returned a repeated non-empty page.",
                        page_index=page_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            seen_pages.add(page_fingerprint)
            jobs.extend(normalized_page)
            raw_job_count += len(parser.rows)

            if page_end >= expected_total:
                if parse_error_count:
                    return _result(
                        source,
                        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                        jobs,
                        page_count,
                        diagnostics,
                    )
                if jobs:
                    diagnostics.append(
                        diagnostic(
                            "missing_publication_date",
                            DiagnosticSeverity.WARNING,
                            "SuccessFactors listing pages omit datePosted; detail retrieval "
                            "supplies it.",
                            count=len(jobs),
                        )
                    )
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page_count,
                    diagnostics,
                    complete=True,
                )
            if page_end <= offset or not parser.rows:
                diagnostics.append(
                    diagnostic(
                        "pagination_stalled",
                        DiagnosticSeverity.ERROR,
                        "SuccessFactors pagination did not advance.",
                        page_index=page_index,
                        observed=page_end,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)
            offset = page_end

        diagnostics.append(
            diagnostic(
                "pagination_limit",
                DiagnosticSeverity.ERROR,
                "SuccessFactors pagination reached the configured page limit.",
                expected=expected_total or 0,
                observed=raw_job_count,
            )
        )
        return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one public RMK detail page without changing listing identity."""
        host, _ = _successfactors_parameters(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("SuccessFactors detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("SuccessFactors detail retrieval requires an external job ID.")
        _validate_job_url(job.canonical_url, host, job.external_job_id)
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
        _validate_job_url(response.final_url, host, job.external_job_id)
        parser = _DetailParser()
        parser.feed(document)
        parser.close()
        title = _required_text(parser.title, "SuccessFactors detail title")
        location = _required_text(parser.location, "SuccessFactors detail location")
        description = _description_text(parser.description_parts)
        published_raw = _optional_text(parser.date_posted)
        published_at = _parse_date_posted(published_raw)
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "datePosted": published_raw,
                "detail_description_missing": description is None,
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
            date_basis=DateBasis.PUBLISHED if published_at is not None else DateBasis.UNKNOWN,
            description=description,
            description_hash=(
                hashlib.sha256(description.encode("utf-8")).hexdigest()
                if description is not None
                else None
            ),
            source_metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class _ListingRow:
    title: str
    href: str | None
    location: str


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ListingRow] = []
        self.pagination_labels: list[str] = []
        self.no_results = False
        self._row: dict[str, object] | None = None
        self._capture_title = False
        self._capture_location = False
        self._capture_pagination = False
        self._pagination_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if attributes.get("id") == "noresults":
            self.no_results = True
        if tag == "span" and "paginationLabel" in classes:
            self._capture_pagination = True
            self._pagination_parts = []
        if tag == "tr" and "data-row" in classes:
            self._row = {"title": [], "href": None, "location": []}
            return
        if self._row is None:
            return
        if tag == "a" and "jobTitle-link" in classes and self._row["href"] is None:
            self._row["href"] = attributes.get("href")
            self._capture_title = True
        if tag == "td" and "colLocation" in classes:
            self._capture_location = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture_pagination:
            label = _compact_text(self._pagination_parts)
            if label:
                self.pagination_labels.append(label)
            self._capture_pagination = False
        if self._row is None:
            return
        if tag == "a" and self._capture_title:
            self._capture_title = False
        elif tag == "td" and self._capture_location:
            self._capture_location = False
        elif tag == "tr":
            self.rows.append(
                _ListingRow(
                    title=_compact_text(self._row["title"]),  # type: ignore[arg-type]
                    href=self._row["href"] if isinstance(self._row["href"], str) else None,
                    location=_compact_text(self._row["location"]),  # type: ignore[arg-type]
                )
            )
            self._row = None
            self._capture_title = False
            self._capture_location = False

    def handle_data(self, data: str) -> None:
        if self._capture_pagination:
            self._pagination_parts.append(data)
        if self._row is not None and self._capture_title:
            title = self._row["title"]
            if isinstance(title, list):
                title.append(data)
        if self._row is not None and self._capture_location:
            location = self._row["location"]
            if isinstance(location, list):
                location.append(data)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.location: str | None = None
        self.date_posted: str | None = None
        self.description_parts: list[str] = []
        self._title_parts: list[str] = []
        self._capture_title = False
        self._description_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        itemprop = attributes.get("itemprop")
        if tag == "meta" and itemprop == "streetAddress" and self.location is None:
            self.location = attributes.get("content")
        elif tag == "meta" and itemprop == "datePosted" and self.date_posted is None:
            self.date_posted = attributes.get("content")
        if self._description_depth:
            if tag in _BLOCK_TAGS or tag == "br":
                self.description_parts.append("\n")
            if tag not in _VOID_TAGS:
                self._description_depth += 1
        elif itemprop == "description":
            self._description_depth = 1
        if itemprop == "title" and self.title is None:
            self._capture_title = True
            self._title_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._description_depth:
            if tag in _BLOCK_TAGS:
                self.description_parts.append("\n")
            self._description_depth -= 1
        if tag == "span" and self._capture_title:
            self.title = _compact_text(self._title_parts)
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        if self._description_depth:
            self.description_parts.append(data)
        if self._capture_title:
            self._title_parts.append(data)


def _successfactors_parameters(source: CompanySource) -> tuple[str, str]:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.SUCCESSFACTORS,
        required_parameters=("host", "category_path"),
    )
    host = parameters["host"].strip().lower()
    category_path = parameters["category_path"].strip()
    if not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host:
        raise ValueError("SuccessFactors host must be a public DNS hostname.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("SuccessFactors host must not be an IP address.")
    careers_host = urlsplit(source.careers_url or "").hostname
    if careers_host is None or careers_host.lower() != host:
        raise ValueError("SuccessFactors host must match the configured careers URL.")
    if not _CATEGORY_PATH.fullmatch(category_path):
        raise ValueError(
            "SuccessFactors category_path must be a public /[brand/]go/<name>/<id>/ path."
        )
    if not urlsplit(source.careers_url or "").path.startswith(category_path):
        raise ValueError("SuccessFactors category_path must match the configured careers URL.")
    return host, category_path


def _listing_endpoint(host: str, category_path: str, offset: int) -> str:
    path = category_path if offset == 0 else f"{category_path}{offset}/"
    query = urlencode({"q": "", "sortColumn": "sort_title", "sortDirection": "desc"})
    return f"https://{host}{path}?{query}"


def _pagination_range(labels: list[str]) -> tuple[int, int, int]:
    ranges: set[tuple[int, int, int]] = set()
    for label in labels:
        match = _RESULT_RANGE.search(label)
        if match:
            ranges.add(
                (
                    int(match.group(1).replace(",", "")),
                    int(match.group(2).replace(",", "")),
                    int(match.group(3).replace(",", "")),
                )
            )
    if len(ranges) != 1:
        raise ValueError("SuccessFactors response requires one consistent result range and total.")
    start, end, total = ranges.pop()
    if start <= 0 or end < start or total < end:
        raise ValueError("SuccessFactors result range and total must be internally consistent.")
    return start, end, total


def _normalize_listing(
    source: CompanySource,
    host: str,
    row: _ListingRow,
    total: int,
    page_start: int,
    page_end: int,
) -> NormalizedJob:
    title = _required_text(row.title, "SuccessFactors listing title")
    location = _required_text(row.location, "SuccessFactors listing location")
    href = _required_text(row.href, "SuccessFactors listing href")
    canonical_url = urljoin(f"https://{host}/", href)
    external_id = _job_id(canonical_url, host)
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.SUCCESSFACTORS.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "listing_total": total,
            "listing_page_start": page_start,
            "listing_page_end": page_end,
        },
    )


def _job_id(url: str, host: str) -> str:
    parsed = urlsplit(url)
    match = _JOB_ID_PATH.search(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != host or match is None:
        raise ValueError("SuccessFactors job URL must use the configured host and numeric job ID.")
    return match.group(1)


def _validate_job_url(url: str, host: str, external_id: str) -> None:
    if _job_id(url, host) != external_id:
        raise ValueError("SuccessFactors detail URL job ID does not match the listing.")


def _parse_date_posted(value: str | None) -> datetime | None:
    if value is None:
        return None
    for pattern in ("%a %b %d %H:%M:%S UTC %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _description_text(parts: list[str]) -> str | None:
    text = "".join(parts).replace("\r", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def _compact_text(parts: list[str]) -> str:
    return _normalize_whitespace(" ".join(parts))


def _required_text(value: object, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field} must be non-empty.")
    return text


def _optional_text(value: object) -> str | None:
    return _normalize_whitespace(value) if isinstance(value, str) and value.strip() else None


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


def _normalize_whitespace(value: str) -> str:
    """Collapse runs of whitespace, preserving case.

    Distinct from the shared ``normalize_text``: several adapters need the original
    casing for display fields such as titles and locations.
    """
    return _WHITESPACE_RUN.sub(" ", value).strip()
