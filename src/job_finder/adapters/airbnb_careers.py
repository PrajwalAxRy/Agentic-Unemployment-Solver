"""Deterministic adapter for Airbnb's public paginated careers pages."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

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

AIRBNB_ADAPTER_KEY = "airbnb_careers_pages"
AIRBNB_CAREERS_URL = "https://careers.airbnb.com/positions/"

_HOST = "careers.airbnb.com"
_PAGE_SIZE = 10
_MAX_PAGES = 50
_DETAIL_PATH_PATTERN = re.compile(r"/positions/([0-9]+)/")
_FWP_ASSIGNMENT = "window.FWP_JSON"
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
    "table",
    "td",
    "tr",
    "ul",
}


@dataclass(frozen=True, slots=True)
class _ListingRow:
    external_id: str
    title: str
    location: str
    canonical_url: str


@dataclass(frozen=True, slots=True)
class _DetailData:
    title: str
    location: str
    description: str
    webpage_date_published: str


@dataclass(frozen=True, slots=True)
class _PagerData:
    page: int
    per_page: int
    total_rows: int
    total_pages: int


class AirbnbCareersAdapter:
    """Read all server-rendered Airbnb pages and defer descriptions until after filtering."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = AIRBNB_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        declared_total: int | None = None
        expected_pages: int | None = None
        page_number = 1

        while expected_pages is None or page_number <= expected_pages:
            if page_number > _MAX_PAGES:
                diagnostics.append(
                    _diagnostic(
                        "pagination_limit",
                        DiagnosticSeverity.ERROR,
                        "Airbnb pagination exceeded the configured safety cap.",
                        max_pages=_MAX_PAGES,
                    )
                )
                return _result(source, AdapterOutcome.PARTIAL, jobs, diagnostics, page_number - 1)
            page_url = _page_url(page_number)
            try:
                if page_number == 1:
                    response = self._client.get(
                        page_url,
                        accepted_content_types=("text/html",),
                        referer=AIRBNB_CAREERS_URL,
                    )
                else:
                    response = self._client.post_json(
                        page_url,
                        _pagination_payload(page_number),
                        accepted_content_types=("application/json",),
                        referer=AIRBNB_CAREERS_URL,
                    )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    _request_outcome(error) if not jobs else AdapterOutcome.PARTIAL,
                    jobs,
                    diagnostics,
                    page_number - 1,
                )
            if response.final_url != page_url:
                diagnostics.append(
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "Airbnb careers page redirected outside its canonical page.",
                        page=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_number,
                )
            try:
                document = response.body.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(
                    _diagnostic(
                        "invalid_encoding",
                        DiagnosticSeverity.ERROR,
                        "Airbnb careers page was not valid UTF-8.",
                        page=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_number,
                )
            if page_number == 1 and is_access_block_html(document):
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
                    diagnostics,
                    page_number,
                )
            try:
                if page_number == 1:
                    parser = _ListingParser()
                    parser.feed(document)
                    parser.close()
                    pager = parser.pager_data()
                else:
                    payload = json.loads(document)
                    if not isinstance(payload, Mapping):
                        raise ValueError("Airbnb pagination response must be a JSON object.")
                    template = payload.get("template")
                    settings = payload.get("settings")
                    if not isinstance(template, str) or not isinstance(settings, Mapping):
                        raise ValueError(
                            "Airbnb pagination response omitted its template or settings."
                        )
                    pager = _pager_data(settings)
                    parser = _ListingParser()
                    parser.feed(template)
                    parser.close()
                rows = parser.rows
            except (json.JSONDecodeError, ValueError) as error:
                diagnostics.append(
                    _diagnostic(
                        "unsupported_schema",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        page=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_number,
                )

            if pager.page != page_number:
                diagnostics.append(
                    _diagnostic(
                        "pagination_page_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Airbnb pagination metadata did not match the requested page.",
                        expected=page_number,
                        observed=pager.page,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_number,
                )

            if declared_total is None:
                declared_total = pager.total_rows
                expected_pages = pager.total_pages
                if expected_pages > _MAX_PAGES:
                    diagnostics.append(
                        _diagnostic(
                            "pagination_limit",
                            DiagnosticSeverity.ERROR,
                            "Airbnb declared total exceeds the configured page safety cap.",
                            declared_total=declared_total,
                            max_pages=_MAX_PAGES,
                        )
                    )
                    return _result(source, AdapterOutcome.FAILED, [], diagnostics, page_number)
            elif pager.total_rows != declared_total or pager.total_pages != expected_pages:
                diagnostics.append(
                    _diagnostic(
                        "inventory_total_changed",
                        DiagnosticSeverity.ERROR,
                        "Airbnb total changed during pagination.",
                        expected=declared_total,
                        observed=pager.total_rows,
                        page=page_number,
                    )
                )
                return _result(source, AdapterOutcome.PARTIAL, jobs, diagnostics, page_number)

            expected_rows = min(
                _PAGE_SIZE,
                max(0, declared_total - ((page_number - 1) * _PAGE_SIZE)),
            )
            if len(rows) != expected_rows:
                diagnostics.append(
                    _diagnostic(
                        "page_count_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Airbnb page row count did not match the declared total.",
                        expected=expected_rows,
                        observed=len(rows),
                        page=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_number,
                )
            for row_index, row in enumerate(rows):
                if row.external_id in seen_ids:
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_job_id",
                            DiagnosticSeverity.ERROR,
                            "Airbnb pagination returned a duplicate job ID.",
                            page=page_number,
                            job_index=row_index,
                        )
                    )
                    return _result(
                        source,
                        AdapterOutcome.SUSPICIOUS,
                        jobs,
                        diagnostics,
                        page_number,
                    )
                seen_ids.add(row.external_id)
                jobs.append(_normalized_listing(source, row, page_number))
            page_number += 1

        if declared_total is None or expected_pages is None:
            raise AssertionError("Airbnb pagination did not initialize")
        if len(jobs) != declared_total:
            diagnostics.append(
                _diagnostic(
                    "inventory_count_mismatch",
                    DiagnosticSeverity.ERROR,
                    "Airbnb collected count did not match the declared total.",
                    expected=declared_total,
                    observed=len(jobs),
                )
            )
            return _result(source, AdapterOutcome.PARTIAL, jobs, diagnostics, expected_pages)
        if jobs:
            diagnostics.append(
                _diagnostic(
                    "unverified_webpage_date_requires_detail",
                    DiagnosticSeverity.WARNING,
                    "Airbnb exposes only an unverified WebPage date on public detail pages.",
                    count=len(jobs),
                )
            )
        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            diagnostics,
            expected_pages,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve and cross-check one public Airbnb detail page."""
        _validate_source(source)
        _validate_job(source, job)
        response = self._client.get(
            job.canonical_url,
            accepted_content_types=("text/html",),
            referer=AIRBNB_CAREERS_URL,
        )
        if response.final_url != job.canonical_url:
            raise DetailIdentityMismatch("Airbnb detail redirected outside its canonical URL.")
        document = response.body.decode("utf-8")
        if is_access_block_html(document):
            raise HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
        parser = _DetailParser()
        parser.feed(document)
        parser.close()
        detail = parser.data(job.canonical_url)
        if _normalize_text(detail.title) != job.title_normalized:
            raise DetailIdentityMismatch("Airbnb detail title does not match the listing.")
        if _normalize_text(detail.location) != _normalize_text(job.location_original):
            raise DetailIdentityMismatch("Airbnb detail location does not match the listing.")
        try:
            webpage_date = datetime.fromisoformat(detail.webpage_date_published).date()
        except ValueError as error:
            raise DetailContentMissing("Airbnb WebPage datePublished is invalid.") from error
        return replace(
            job,
            published_at=webpage_date,
            published_at_raw=detail.webpage_date_published,
            date_basis=DateBasis.UNKNOWN,
            description=detail.description,
            description_hash=hashlib.sha256(detail.description.encode("utf-8")).hexdigest(),
            source_metadata={
                **job.source_metadata,
                "webpage_date_published": detail.webpage_date_published,
                "webpage_date_unverified": True,
                "detail_retrieved": True,
            },
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != AIRBNB_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Airbnb adapter requires adapter_key={AIRBNB_ADAPTER_KEY}."
        )
    if source.careers_url != AIRBNB_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Airbnb adapter requires careers_url={AIRBNB_CAREERS_URL}."
        )


def _validate_job(source: CompanySource, job: NormalizedJob) -> None:
    if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
        raise AdapterConfigurationError("Airbnb detail job does not belong to the source.")
    canonical_url, external_id = _canonical_detail_url(job.canonical_url)
    if canonical_url != job.canonical_url or external_id != job.external_job_id:
        raise AdapterConfigurationError("Airbnb detail job identity is inconsistent.")


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.script_depth = 0
        self.current_script_parts: list[str] = []
        self.fwp_scripts: list[str] = []
        self.item_depth = 0
        self.anchor_depth = 0
        self.location_depth = 0
        self.title_parts: list[str] = []
        self.location_parts: list[str] = []
        self.detail_url: str | None = None
        self.rows: list[_ListingRow] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        tag = tag.casefold()
        if self.script_depth:
            self.script_depth += 1
        elif tag == "script":
            self.script_depth = 1
            self.current_script_parts = []

        if self.item_depth == 0:
            if tag == "li" and attributes.get("role") == "listitem" and "inner-grid" in classes:
                self.item_depth = 1
                self.anchor_depth = 0
                self.location_depth = 0
                self.title_parts = []
                self.location_parts = []
                self.detail_url = None
            return

        self.item_depth += 1
        if self.anchor_depth:
            self.anchor_depth += 1
        if self.location_depth:
            self.location_depth += 1
        if tag == "a":
            href = attributes.get("href")
            if isinstance(href, str) and _is_detail_url(href):
                self.detail_url = href
                self.anchor_depth = 1
        elif tag == "div" and {"lg:col-span-3", "justify-end", "text-right"}.issubset(classes):
            self.location_depth = 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self.script_depth:
            self.script_depth -= 1
            if self.script_depth == 0:
                script = "".join(self.current_script_parts)
                if _FWP_ASSIGNMENT in script:
                    self.fwp_scripts.append(script)
        if not self.item_depth:
            return
        if self.anchor_depth:
            self.anchor_depth -= 1
        if self.location_depth:
            self.location_depth -= 1
        self.item_depth -= 1
        if self.item_depth == 0:
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self.script_depth:
            self.current_script_parts.append(data)
        if self.anchor_depth:
            self.title_parts.append(data)
        if self.location_depth:
            self.location_parts.append(data)

    def _finish_row(self) -> None:
        title = _normalize_whitespace(" ".join(self.title_parts))
        location = _normalize_whitespace(" ".join(self.location_parts))
        if self.detail_url is None or not title or not location:
            raise ValueError("Airbnb listing row omitted its URL, title, or location.")
        canonical_url, external_id = _canonical_detail_url(self.detail_url)
        self.rows.append(_ListingRow(external_id, title, location, canonical_url))

    def pager_data(self) -> _PagerData:
        if len(self.fwp_scripts) != 1:
            raise ValueError("Airbnb listing must expose exactly one FWP pagination payload.")
        script = self.fwp_scripts[0]
        marker = script.index(_FWP_ASSIGNMENT) + len(_FWP_ASSIGNMENT)
        assignment = script.find("=", marker)
        if assignment < 0:
            raise ValueError("Airbnb FWP pagination payload omitted its assignment.")
        raw = script[assignment + 1 :].lstrip()
        try:
            payload, end = json.JSONDecoder().raw_decode(raw)
        except json.JSONDecodeError as error:
            raise ValueError("Airbnb FWP pagination payload was not valid JSON.") from error
        if not isinstance(payload, Mapping):
            raise ValueError("Airbnb FWP pagination payload had an unsupported shape.")
        _validate_fwp_script_tail(raw[end:])
        preload_data = payload.get("preload_data")
        if not isinstance(preload_data, Mapping):
            raise ValueError("Airbnb FWP payload omitted preload_data.")
        settings = preload_data.get("settings")
        if not isinstance(settings, Mapping):
            raise ValueError("Airbnb FWP payload omitted pagination settings.")
        return _pager_data(settings)


def _validate_fwp_script_tail(value: str) -> None:
    tail = value.strip()
    if tail in {"", ";"}:
        return
    http_assignment = "window.FWP_HTTP"
    if not tail.startswith(";"):
        raise ValueError("Airbnb FWP pagination script had unexpected trailing content.")
    tail = tail[1:].lstrip()
    if not tail.startswith(http_assignment):
        raise ValueError("Airbnb FWP pagination script had unexpected trailing content.")
    assignment = tail.find("=", len(http_assignment))
    if assignment < 0:
        raise ValueError("Airbnb FWP HTTP payload omitted its assignment.")
    raw = tail[assignment + 1 :].lstrip()
    try:
        payload, end = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Airbnb FWP HTTP payload was not valid JSON.") from error
    if not isinstance(payload, Mapping) or raw[end:].strip() not in {"", ";"}:
        raise ValueError("Airbnb FWP HTTP payload had an unsupported shape.")


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.banner_depth = 0
        self.title_depth = 0
        self.location_depth = 0
        self.detail_depth = 0
        self.schema_depth = 0
        self.title_parts: list[str] = []
        self.location_parts: list[str] = []
        self.detail_parts: list[str] = []
        self.schema_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        tag = tag.casefold()
        if self.banner_depth:
            self.banner_depth += 1
        elif tag == "div" and "job-page-banner" in classes:
            self.banner_depth = 1
        if self.banner_depth and tag == "h1" and not self.title_depth:
            self.title_depth = 1
        elif self.title_depth:
            self.title_depth += 1
        if self.banner_depth and tag == "div" and "offices" in classes and not self.location_depth:
            self.location_depth = 1
        elif self.location_depth:
            self.location_depth += 1

        if self.detail_depth:
            self.detail_depth += 1
            if tag in _BLOCK_TAGS:
                self.detail_parts.append("\n")
        elif (
            tag == "div" and attributes.get("id") == "job-detail-panel" and "job-detail" in classes
        ):
            self.detail_depth = 1
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self.schema_depth = 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self.schema_depth and tag == "script":
            self.schema_depth = 0
        if self.title_depth:
            self.title_depth -= 1
        if self.location_depth:
            self.location_depth -= 1
        if self.banner_depth:
            self.banner_depth -= 1
        if self.detail_depth:
            if tag in _BLOCK_TAGS:
                self.detail_parts.append("\n")
            self.detail_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.schema_depth:
            self.schema_parts.append(data)
        if self.title_depth:
            self.title_parts.append(data)
        if self.location_depth:
            self.location_parts.append(data)
        if self.detail_depth:
            self.detail_parts.append(data)

    def data(self, canonical_url: str) -> _DetailData:
        title = _normalize_whitespace(" ".join(self.title_parts))
        location = _normalize_whitespace(" ".join(self.location_parts))
        description = "\n".join(
            line
            for line in (
                _normalize_whitespace(part) for part in "".join(self.detail_parts).splitlines()
            )
            if line
        )
        if not title or not location or len(description) < 80:
            raise ValueError("Airbnb detail omitted its title, location, or full description.")
        date_published = _webpage_date(self.schema_parts, canonical_url, title)
        return _DetailData(title, location, description, date_published)


def _webpage_date(schema_parts: list[str], canonical_url: str, title: str) -> str:
    matches: list[str] = []
    for raw in schema_parts:
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("Airbnb structured metadata was not valid JSON.") from error
        if not isinstance(payload, Mapping):
            continue
        graph = payload.get("@graph")
        if not isinstance(graph, list):
            continue
        for item in graph:
            if not isinstance(item, Mapping) or item.get("@type") != "WebPage":
                continue
            if item.get("url") != canonical_url:
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.startswith(title):
                raise ValueError("Airbnb WebPage metadata title does not match the detail.")
            value = item.get("datePublished")
            if isinstance(value, str) and value.strip():
                matches.append(value.strip())
    if len(matches) != 1:
        raise ValueError("Airbnb detail must expose exactly one WebPage datePublished value.")
    return matches[0]


def _normalized_listing(
    source: CompanySource,
    row: _ListingRow,
    page_number: int,
) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=row.external_id,
        title_original=row.title,
        title_normalized=_normalize_text(row.title),
        location_original=row.location,
        location_normalized=tuple(
            dict.fromkeys(
                _normalize_text(part) for part in re.split(r"[,|;/]", row.location) if part.strip()
            )
        ),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=row.canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": AIRBNB_ADAPTER_KEY,
            "listing_page": page_number,
        },
    )


def _page_url(page_number: int) -> str:
    return AIRBNB_CAREERS_URL if page_number == 1 else f"{AIRBNB_CAREERS_URL}?_paged={page_number}"


def _pagination_payload(page_number: int) -> dict[str, object]:
    page = str(page_number)
    return {
        "action": "facetwp_refresh",
        "data": {
            "facets": {
                "jobs_total": [],
                "search_input": "",
                "departments": [],
                "where_you_work": [],
                "workplace_type": [],
                "jobs_pager": [],
                "jobs_sort": [],
                "jobs_pagination": [],
            },
            "frozen_facets": {},
            "http_params": {
                "get": {"_paged": page},
                "uri": "positions",
                "url_vars": [],
                "lang": "en",
            },
            "template": "wp",
            "extras": {"sort": "default"},
            "soft_refresh": 1,
            "is_bfcache": 1,
            "first_load": 0,
            "paged": page,
        },
    }


def _pager_data(settings: Mapping[str, object]) -> _PagerData:
    raw_pager = settings.get("pager")
    if not isinstance(raw_pager, Mapping):
        raise ValueError("Airbnb pagination settings omitted pager metadata.")
    page = _pager_integer(raw_pager, "page", positive=True)
    per_page = _pager_integer(raw_pager, "per_page", positive=True)
    total_rows = _pager_integer(raw_pager, "total_rows", positive=False)
    total_pages = _pager_integer(raw_pager, "total_pages", positive=False)
    expected_pages = max(1, math.ceil(total_rows / _PAGE_SIZE))
    if per_page != _PAGE_SIZE or total_pages != expected_pages:
        raise ValueError("Airbnb pagination metadata was internally inconsistent.")
    return _PagerData(page, per_page, total_rows, total_pages)


def _pager_integer(
    pager: Mapping[str, object],
    field: str,
    *,
    positive: bool,
) -> int:
    value = pager.get(field)
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"Airbnb pager {field} must be an integer of at least {minimum}.")
    return value


def _is_detail_url(value: str) -> bool:
    try:
        _canonical_detail_url(value)
    except ValueError:
        return False
    return True


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
        raise ValueError("Airbnb detail URL must be a canonical same-origin position URL.")
    external_id = match.group(1)
    return f"https://{_HOST}/positions/{external_id}/", external_id


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text(value: str) -> str:
    return _normalize_whitespace(value).casefold()


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
    diagnostics: list[AdapterDiagnostic],
    page_count: int,
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
