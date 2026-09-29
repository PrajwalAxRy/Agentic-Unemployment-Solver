"""Deterministic adapter for Intuit's public Bengaluru TalentBrew pages."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from job_finder.adapters._support import diagnostic, request_outcome
from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpRequestError
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
    normalize_text,
    normalize_title,
)

_WHITESPACE_RUN = re.compile(r"\s+")

INTUIT_ADAPTER_KEY = "intuit_bengaluru_pages"
INTUIT_CAREERS_URL = (
    "https://jobs.intuit.com/location/bengaluru-jobs/27595/1269750-1267701-1277333/4"
)

_HOST = "jobs.intuit.com"
_PAGE_SIZE = 15
_MAX_PAGES = 10
_DETAIL_PATH = re.compile(r"/job/[^/]+/[^/]+/27595/([0-9]+)")
_COUNT_HEADING = re.compile(r"([0-9,]+) jobs found in Bengaluru", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _ListingRow:
    external_id: str
    title: str
    location: str
    category: str | None
    canonical_url: str


class IntuitCareersAdapter:
    """Read Intuit's complete Bengaluru-filtered inventory and deferred details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = INTUIT_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None
        expected_pages: int | None = None
        page_number = 1

        while expected_pages is None or page_number <= expected_pages:
            if page_number > _MAX_PAGES:
                return _failed_or_partial(
                    source,
                    jobs,
                    diagnostics,
                    "pagination_limit",
                    "Intuit pagination exceeded the configured safety cap.",
                    page_count=page_number - 1,
                )
            page_url = _page_url(page_number)
            try:
                response = self._client.get(
                    page_url,
                    accepted_content_types=("text/html",),
                    referer=INTUIT_CAREERS_URL,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else request_outcome(error),
                    jobs,
                    diagnostics,
                    page_count=page_number - 1,
                )
            if response.final_url != page_url:
                return _failed_or_partial(
                    source,
                    jobs,
                    diagnostics,
                    "unexpected_redirect",
                    "Intuit careers page redirected.",
                    page_count=page_number,
                )
            try:
                document = response.body.decode("utf-8")
            except UnicodeDecodeError:
                return _failed_or_partial(
                    source,
                    jobs,
                    diagnostics,
                    "invalid_encoding",
                    "Intuit careers page was not valid UTF-8.",
                    page_count=page_number,
                )
            if is_access_block_html(document):
                diagnostics.append(
                    diagnostic(
                        "access_block",
                        DiagnosticSeverity.ERROR,
                        "Intuit careers returned an access-control page.",
                        page=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.BLOCKED,
                    jobs,
                    diagnostics,
                    page_count=page_number,
                )
            try:
                parser = _ListingParser()
                parser.feed(document)
                parser.close()
                total, pages, current = parser.pagination()
                rows = parser.rows
            except ValueError as error:
                return _failed_or_partial(
                    source,
                    jobs,
                    diagnostics,
                    "unsupported_schema",
                    str(error),
                    page_count=page_number,
                )
            if current != page_number:
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    "pagination_page_mismatch",
                    "Intuit pagination metadata did not match the requested page.",
                    page_count=page_number,
                )
            if pages != math.ceil(total / _PAGE_SIZE):
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    "pagination_count_mismatch",
                    "Intuit total and page-count metadata disagreed.",
                    page_count=page_number,
                )
            if expected_total is None:
                expected_total, expected_pages = total, pages
            elif total != expected_total or pages != expected_pages:
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    "inconsistent_pagination",
                    "Intuit pagination metadata changed during collection.",
                    page_count=page_number,
                )
            expected_page_size = min(_PAGE_SIZE, total - len(jobs))
            if len(rows) != expected_page_size:
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    "incomplete_page",
                    "Intuit page size did not match the declared inventory.",
                    page_count=page_number,
                )

            for row in rows:
                if row.external_id in seen_ids:
                    return _suspicious(
                        source,
                        jobs,
                        diagnostics,
                        "duplicate_job_id",
                        "Intuit pagination returned a duplicate job ID.",
                        page_count=page_number,
                    )
                seen_ids.add(row.external_id)
                jobs.append(_normalize_listing(source, row))
            page_number += 1

        if expected_total is None or len(jobs) != expected_total:
            return _suspicious(
                source,
                jobs,
                diagnostics,
                "incomplete_collection",
                "Intuit collected count did not match its declared total.",
                page_count=page_number - 1,
            )
        diagnostics.append(
            diagnostic(
                "publication_date_requires_detail",
                DiagnosticSeverity.WARNING,
                "Intuit exposes its verified datePosted value only on job detail pages.",
                count=len(jobs),
            )
        )
        return _result(
            source,
            AdapterOutcome.SUCCESS,
            jobs,
            diagnostics,
            page_count=page_number - 1,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        _validate_source(source)
        _validate_listing_job(source, job)
        try:
            response = self._client.get(
                job.canonical_url,
                accepted_content_types=("text/html",),
                referer=INTUIT_CAREERS_URL,
            )
        except HttpRequestError as error:
            raise ValueError(f"Intuit detail request failed: {error.category.value}") from error
        if response.final_url != job.canonical_url:
            raise ValueError("Intuit detail redirected outside its canonical URL.")
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Intuit detail was not valid UTF-8.") from error
        if is_access_block_html(document):
            raise ValueError("Intuit detail returned an access-control page.")
        parser = _JsonLdParser()
        parser.feed(document)
        parser.close()
        detail = parser.job_posting()
        return _normalize_detail(job, detail)


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != INTUIT_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Intuit adapter requires adapter_key={INTUIT_ADAPTER_KEY}."
        )
    if source.careers_url != INTUIT_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Intuit adapter requires careers_url={INTUIT_CAREERS_URL}."
        )


def _validate_listing_job(source: CompanySource, job: NormalizedJob) -> None:
    if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
        raise AdapterConfigurationError("Intuit detail job does not belong to the source.")
    external_id = job.external_job_id
    if external_id is None or _external_id(job.canonical_url) != external_id:
        raise AdapterConfigurationError("Intuit detail job identity is inconsistent.")


def _page_url(page_number: int) -> str:
    return INTUIT_CAREERS_URL if page_number == 1 else f"{INTUIT_CAREERS_URL}/{page_number}"


def _normalize_listing(source: CompanySource, row: _ListingRow) -> NormalizedJob:
    raw_location = _normalize_whitespace(row.location)
    location = (
        "Bangalore, India | Multiple Locations"
        if raw_location.casefold() == "multiple locations"
        else raw_location
    )
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=row.external_id,
        title_original=_normalize_whitespace(row.title),
        title_normalized=normalize_title(row.title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=row.canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": INTUIT_ADAPTER_KEY,
            "category": row.category,
            "listing_location_original": raw_location,
            "bengaluru_filter_verified": True,
        },
    )


def _normalize_detail(job: NormalizedJob, raw: Mapping[str, object]) -> NormalizedJob:
    if raw.get("@type") != "JobPosting":
        raise ValueError("Intuit detail JSON-LD was not a JobPosting.")
    if _required_string(raw, "title", "Intuit detail") != job.title_original:
        raise ValueError("Intuit detail title did not match the listing.")
    if _required_string(raw, "url", "Intuit detail") != job.canonical_url:
        raise ValueError("Intuit detail URL did not match the listing.")
    organization = raw.get("hiringOrganization")
    if not isinstance(organization, Mapping) or organization.get("name") != "Intuit":
        raise ValueError("Intuit detail hiring organization was invalid.")
    locations = _detail_locations(raw.get("jobLocation"))
    if not any(_is_bengaluru_india(location) for location in locations):
        raise ValueError("Intuit detail did not retain the Bengaluru filter location.")
    description = _html_text(_required_string(raw, "description", "Intuit detail"))
    if len(description) < 80:
        raise ValueError("Intuit detail description normalized to insufficient text.")
    date_raw = _required_string(raw, "datePosted", "Intuit detail")
    try:
        published_at = datetime.strptime(date_raw, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Intuit detail datePosted was invalid.") from error
    return NormalizedJob(
        schema_version=1,
        company_id=job.company_id,
        source_type=job.source_type,
        external_job_id=job.external_job_id,
        title_original=job.title_original,
        title_normalized=job.title_normalized,
        location_original=" | ".join(locations),
        location_normalized=_shared_locations(locations),
        published_at=published_at,
        published_at_raw=date_raw,
        date_basis=DateBasis.PUBLISHED,
        canonical_url=job.canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            **job.source_metadata,
            "detail_retrieved": True,
            "detail_identifier": raw.get("identifier"),
            "employment_type": raw.get("employmentType"),
        },
    )


def _detail_locations(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        if not isinstance(item, Mapping):
            raise ValueError("Intuit jobLocation entries must be objects.")
        address = item.get("address")
        if not isinstance(address, Mapping):
            raise ValueError("Intuit jobLocation address must be an object.")
        parts = [
            _optional_string(address.get("addressLocality")),
            _optional_string(address.get("addressRegion")),
            _optional_string(address.get("addressCountry")),
        ]
        location = ", ".join(part for part in parts if part)
        if not location:
            raise ValueError("Intuit jobLocation address was empty.")
        if location.casefold() not in {item.casefold() for item in result}:
            result.append(location)
    if not result:
        raise ValueError("Intuit detail exposed no job locations.")
    return result


def _is_bengaluru_india(location: str) -> bool:
    # casefold() is explicit here: the shared normalize_text normalizes Unicode, entities
    # and whitespace but deliberately preserves case (normalize_title is the case-folding
    # one). The local helper this replaced folded case, and these comparands are lowercase
    # literals.
    normalized = normalize_text(location).casefold()
    return "india" in normalized and any(city in normalized for city in ("bengaluru", "bangalore"))


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ListingRow] = []
        self._heading_depth = 0
        self._heading_parts: list[str] = []
        self._headings: list[str] = []
        self._category: str | None = None
        self._row_href: str | None = None
        self._row_title: str | None = None
        self._row_location_parts: list[str] = []
        self._in_location = False
        self.current_page: int | None = None
        self.total_pages: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "section" and values.get("data-current-page"):
            self.current_page = _positive_text_int(
                values.get("data-current-page"), "Intuit current page"
            )
            per_page = _positive_text_int(
                values.get("data-records-per-page"), "Intuit records per page"
            )
            if per_page != _PAGE_SIZE:
                raise ValueError("Intuit records-per-page changed from 15.")
        elif tag == "input" and "pagination-current" in classes:
            self.total_pages = _positive_text_int(values.get("max"), "Intuit total pages")
        elif tag == "h1":
            self._heading_depth += 1
            self._heading_parts = []
        elif tag == "li" and values.get("data-category") is not None:
            self._category = _optional_string(values.get("data-category"))
        elif tag == "a" and "sr-item" in classes:
            self._row_href = values.get("href")
            self._row_title = values.get("data-title")
            self._row_location_parts = []
        elif self._row_href is not None and tag == "span" and "job-location" in classes:
            self._in_location = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._heading_depth:
            self._heading_depth -= 1
            self._headings.append(_normalize_whitespace(" ".join(self._heading_parts)))
        elif tag == "span" and self._in_location:
            self._in_location = False
        elif tag == "a" and self._row_href is not None:
            self.rows.append(
                _listing_row(
                    self._row_href,
                    self._row_title,
                    " ".join(self._row_location_parts),
                    self._category,
                )
            )
            self._row_href = None
            self._row_title = None
            self._row_location_parts = []
        elif tag == "li":
            self._category = None

    def handle_data(self, data: str) -> None:
        if self._heading_depth:
            self._heading_parts.append(data)
        if self._in_location:
            self._row_location_parts.append(data)

    def pagination(self) -> tuple[int, int, int]:
        total: int | None = None
        for heading in self._headings:
            match = _COUNT_HEADING.fullmatch(heading)
            if match:
                total = int(match.group(1).replace(",", ""))
                break
        if total is None or total <= 0:
            raise ValueError("Intuit page omitted its positive Bengaluru job count.")
        if self.total_pages is None or self.current_page is None:
            raise ValueError("Intuit page omitted pagination metadata.")
        return total, self.total_pages, self.current_page


def _listing_row(
    href: str | None,
    title: str | None,
    location: str,
    category: str | None,
) -> _ListingRow:
    if href is None or title is None:
        raise ValueError("Intuit listing row omitted its URL or title.")
    canonical_url = href if href.startswith("https://") else f"https://{_HOST}{href}"
    external_id = _external_id(canonical_url)
    if not title.strip() or not location.strip():
        raise ValueError("Intuit listing row omitted its title or location.")
    return _ListingRow(external_id, title, location, category, canonical_url)


def _external_id(value: str) -> str:
    parsed = urlsplit(value)
    match = _DETAIL_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _HOST
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("Intuit detail URL did not match the verified canonical pattern.")
    return match.group(1)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capture = False
        self._parts: list[str] = []
        self._values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._capture = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture:
            self._values.append("".join(self._parts))
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def job_posting(self) -> Mapping[str, object]:
        candidates: list[Mapping[str, object]] = []
        for value in self._values:
            try:
                payload: Any = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping) and payload.get("@type") == "JobPosting":
                candidates.append(payload)
        if len(candidates) != 1:
            raise ValueError("Intuit detail must expose exactly one JobPosting JSON-LD object.")
        return candidates[0]


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "svg", "noscript"}:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag.casefold() in {"br", "div", "li", "p"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif self.skip_depth == 0 and tag.casefold() in {"div", "li", "p"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def _html_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    return _normalize_whitespace("".join(parser.parts))


def _positive_text_int(value: str | None, context: str) -> int:
    if value is None:
        raise ValueError(f"{context} was missing.")
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{context} must be an integer.") from error
    if parsed <= 0:
        raise ValueError(f"{context} must be positive.")
    return parsed


def _required_string(raw: Mapping[str, object], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} {field} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return _normalize_whitespace(value) if isinstance(value, str) and value.strip() else None


def _failed_or_partial(
    source: CompanySource,
    jobs: list[NormalizedJob],
    diagnostics: list[AdapterDiagnostic],
    category: str,
    message: str,
    *,
    page_count: int,
) -> AdapterResult:
    diagnostics.append(diagnostic(category, DiagnosticSeverity.ERROR, message))
    return _result(
        source,
        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
        jobs,
        diagnostics,
        page_count=page_count,
    )


def _suspicious(
    source: CompanySource,
    jobs: list[NormalizedJob],
    diagnostics: list[AdapterDiagnostic],
    category: str,
    message: str,
    *,
    page_count: int,
) -> AdapterResult:
    diagnostics.append(diagnostic(category, DiagnosticSeverity.ERROR, message))
    return _result(
        source,
        AdapterOutcome.SUSPICIOUS,
        jobs,
        diagnostics,
        page_count=page_count,
    )


def _result(
    source: CompanySource,
    outcome: AdapterOutcome,
    jobs: list[NormalizedJob],
    diagnostics: list[AdapterDiagnostic],
    *,
    page_count: int,
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
