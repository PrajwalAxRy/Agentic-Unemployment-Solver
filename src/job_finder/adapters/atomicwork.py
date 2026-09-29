"""Bounded custom adapter for Atomicwork's public Webflow careers pages."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

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

ATOMICWORK_ADAPTER_KEY = "atomicwork_webflow"
ATOMICWORK_HOST = "www.atomicwork.com"
ATOMICWORK_CAREERS_URL = f"https://{ATOMICWORK_HOST}/company/careers"
ATOMICWORK_SITEMAP_URL = f"https://{ATOMICWORK_HOST}/sitemap.xml"

_DETAIL_PATH_PATTERN = re.compile(r"/careers/([A-Za-z0-9][A-Za-z0-9-]*)/?")
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


class AtomicworkWebflowAdapter:
    """Retrieve Atomicwork's official Webflow inventory and deferred job details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = ATOMICWORK_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        diagnostics: list[AdapterDiagnostic] = []
        try:
            response = self._client.get(
                ATOMICWORK_CAREERS_URL,
                accepted_content_types=("text/html",),
                referer=ATOMICWORK_CAREERS_URL,
            )
        except HttpRequestError as error:
            diagnostics.append(request_failure_diagnostic(error))
            return _result(source, _request_outcome(error), [], diagnostics, page_count=0)

        document = _decode_utf8(response.body, "Atomicwork careers response", diagnostics)
        if document is None:
            return _result(source, AdapterOutcome.FAILED, [], diagnostics, page_count=1)
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
            return _result(source, AdapterOutcome.BLOCKED, [], diagnostics, page_count=1)
        if not _same_url(response.final_url, ATOMICWORK_CAREERS_URL):
            diagnostics.append(
                _diagnostic(
                    "unexpected_redirect",
                    DiagnosticSeverity.ERROR,
                    "Atomicwork careers request redirected outside the approved listing URL.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics, page_count=1)

        parser = _ListingParser()
        parser.feed(document)
        parser.close()
        if not parser.has_open_positions_heading or not parser.has_list_marker:
            diagnostics.append(
                _diagnostic(
                    "unsupported_schema",
                    DiagnosticSeverity.ERROR,
                    "Atomicwork careers response omitted required Webflow listing markers.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics, page_count=1)

        jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()
        for job_index, row in enumerate(parser.rows):
            try:
                job = _normalize_listing(source, row)
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=job_index,
                    )
                )
                continue
            if job.external_job_id in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Atomicwork returned a duplicate path-derived job ID.",
                        job_index=job_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    diagnostics,
                    page_count=1,
                )
            if job.external_job_id is not None:
                seen_ids.add(job.external_job_id)
            jobs.append(job)

        if len(jobs) != len(parser.rows):
            return _result(
                source,
                AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                jobs,
                diagnostics,
                page_count=1,
            )
        if not jobs and not parser.explicit_empty:
            diagnostics.append(
                _diagnostic(
                    "unexplained_empty_page",
                    DiagnosticSeverity.ERROR,
                    "Atomicwork returned no jobs without Webflow's explicit empty state.",
                )
            )
            return _result(
                source,
                AdapterOutcome.SUSPICIOUS,
                [],
                diagnostics,
                page_count=1,
            )

        try:
            sitemap_response = self._client.get(
                ATOMICWORK_SITEMAP_URL,
                accepted_content_types=("application/rss+xml", "application/xml", "text/xml"),
                referer=ATOMICWORK_CAREERS_URL,
            )
        except HttpRequestError as error:
            diagnostics.append(request_failure_diagnostic(error))
            return _result(source, _request_outcome(error), jobs, diagnostics, page_count=1)
        if not _same_url(sitemap_response.final_url, ATOMICWORK_SITEMAP_URL):
            diagnostics.append(
                _diagnostic(
                    "unexpected_redirect",
                    DiagnosticSeverity.ERROR,
                    "Atomicwork sitemap redirected outside the approved public sitemap URL.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, jobs, diagnostics, page_count=2)
        sitemap_document = _decode_utf8(
            sitemap_response.body,
            "Atomicwork sitemap response",
            diagnostics,
        )
        if sitemap_document is None:
            return _result(source, AdapterOutcome.FAILED, jobs, diagnostics, page_count=2)
        try:
            sitemap_urls = _sitemap_job_urls(sitemap_document)
        except ValueError as error:
            diagnostics.append(
                _diagnostic(
                    "malformed_sitemap",
                    DiagnosticSeverity.ERROR,
                    str(error),
                )
            )
            return _result(source, AdapterOutcome.FAILED, jobs, diagnostics, page_count=2)

        listing_urls = {job.canonical_url for job in jobs}
        if listing_urls != sitemap_urls:
            diagnostics.append(
                _diagnostic(
                    "listing_sitemap_mismatch",
                    DiagnosticSeverity.ERROR,
                    "Atomicwork's careers listing and public sitemap job inventories disagree.",
                    listing_count=len(listing_urls),
                    sitemap_count=len(sitemap_urls),
                    listing_only=len(listing_urls - sitemap_urls),
                    sitemap_only=len(sitemap_urls - listing_urls),
                )
            )
            return _result(
                source,
                AdapterOutcome.SUSPICIOUS,
                jobs,
                diagnostics,
                page_count=2,
            )
        if not jobs:
            return _result(
                source,
                AdapterOutcome.EMPTY,
                [],
                diagnostics,
                page_count=2,
                complete=True,
            )

        diagnostics.append(
            _diagnostic(
                "missing_publication_date",
                DiagnosticSeverity.WARNING,
                "Atomicwork exposes no trustworthy job publication date.",
                count=len(jobs),
            )
        )
        return _result(
            source,
            AdapterOutcome.SUCCESS,
            jobs,
            diagnostics,
            page_count=2,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one official Atomicwork detail page without changing job identity."""
        _validate_source(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise DetailIdentityMismatch(
                "Atomicwork detail job does not match the configured source."
            )
        if job.external_job_id is None:
            raise DetailContentMissing("Atomicwork detail retrieval requires an external job ID.")
        canonical_url, external_id = _canonical_detail_url(job.canonical_url)
        if canonical_url != job.canonical_url or external_id != job.external_job_id:
            raise DetailIdentityMismatch(
                "Atomicwork detail URL identity does not match the listing."
            )

        response = self._client.get(
            job.canonical_url,
            accepted_content_types=("text/html",),
            referer=ATOMICWORK_CAREERS_URL,
        )
        document = response.body.decode("utf-8")
        if is_access_block_html(document):
            raise HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
        if not _same_url(response.final_url, job.canonical_url):
            raise DetailIdentityMismatch(
                "Atomicwork detail response URL does not match the listing."
            )

        parser = _DetailParser()
        parser.feed(document)
        parser.close()
        title = _required_text(_compact_text(parser.title_parts), "Atomicwork detail title")
        if _normalize_text(title) != job.title_normalized:
            raise DetailIdentityMismatch(
                "Atomicwork detail title does not match the listing title."
            )
        location = _required_text(
            _compact_text(parser.location_parts),
            "Atomicwork detail location",
        )
        description = _plain_text(parser.description_parts)
        if description is None:
            raise DetailContentMissing("Atomicwork detail description must be non-empty.")
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "detail_department": _optional_text(parser.department_parts),
                "application_url": parser.application_url,
            }
        )
        return replace(
            job,
            title_original=title,
            title_normalized=_normalize_text(title),
            location_original=location,
            location_normalized=_normalized_locations(location),
            published_at=None,
            published_at_raw=None,
            date_basis=DateBasis.UNKNOWN,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class _ListingRow:
    title: str
    location: str
    href: str | None
    department: str | None


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ListingRow] = []
        self.has_open_positions_heading = False
        self.has_list_marker = False
        self.explicit_empty = False
        self._heading_parts: list[str] = []
        self._capture_heading = False
        self._item: dict[str, object] | None = None
        self._item_div_depth = 0
        self._capture_title = False
        self._department_depth: int | None = None
        self._location_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag in {"h1", "h2", "h3"} and "heading_h2" in classes:
            self._capture_heading = True
            self._heading_parts = []
        if tag == "div" and attributes.get("fs-cmsfilter-element") == "list":
            self.has_list_marker = True
        if tag == "div" and "w-dyn-empty" in classes:
            self.explicit_empty = True

        if tag == "div" and "oj-item" in classes and self._item is None:
            self._item = {"title": [], "location": [], "department": [], "href": None}
            self._item_div_depth = 1
        elif self._item is not None and tag == "div":
            self._item_div_depth += 1

        if self._item is None:
            return
        if tag == "h4" and "h4" in classes:
            self._capture_title = True
        if tag == "div" and attributes.get("fs-cmsfilter-field") == "department":
            self._department_depth = self._item_div_depth
        if tag == "div" and "location" in classes:
            self._location_depth = self._item_div_depth
        if tag == "a" and "secondary_cta" in classes:
            self._item["href"] = attributes.get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"} and self._capture_heading:
            self.has_open_positions_heading = (
                _compact_text(self._heading_parts).casefold() == "open positions"
            )
            self._capture_heading = False
        if self._item is None:
            return
        if tag == "h4":
            self._capture_title = False
        if tag != "div":
            return
        if self._department_depth == self._item_div_depth:
            self._department_depth = None
        if self._location_depth == self._item_div_depth:
            self._location_depth = None
        self._item_div_depth -= 1
        if self._item_div_depth != 0:
            return
        self.rows.append(
            _ListingRow(
                title=_compact_object_parts(self._item["title"]),
                location=_compact_object_parts(self._item["location"]),
                href=self._item["href"] if isinstance(self._item["href"], str) else None,
                department=_optional_object_parts(self._item["department"]),
            )
        )
        self._item = None
        self._capture_title = False
        self._department_depth = None
        self._location_depth = None

    def handle_data(self, data: str) -> None:
        if self._capture_heading:
            self._heading_parts.append(data)
        if self._item is None:
            return
        if self._capture_title:
            _append_object_part(self._item["title"], data)
        if self._department_depth is not None:
            _append_object_part(self._item["department"], data)
        if self._location_depth is not None:
            _append_object_part(self._item["location"], data)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.location_parts: list[str] = []
        self.department_parts: list[str] = []
        self.description_parts: list[str] = []
        self.application_url: str | None = None
        self._capture_title = False
        self._capture_location = False
        self._capture_department = False
        self._description_div_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "h2" and "heading_h2" in classes and not self.title_parts:
            self._capture_title = True
        if tag == "div" and "loation_txt" in classes and not self.location_parts:
            self._capture_location = True
        if tag == "div" and "page-tag" in classes and not self.department_parts:
            self._capture_department = True
        if tag == "div" and {"blog-rich-text", "w-richtext"}.issubset(classes):
            self._description_div_depth = 1
        elif self._description_div_depth and tag == "div":
            self._description_div_depth += 1
        if self._description_div_depth and (tag in _BLOCK_TAGS or tag == "br"):
            self.description_parts.append("\n")
        if tag == "a" and "primary_cta" in classes:
            href = attributes.get("href")
            if isinstance(href, str) and href.strip():
                self.application_url = href.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._capture_title:
            self._capture_title = False
        if tag == "div" and self._capture_location:
            self._capture_location = False
        if tag == "div" and self._capture_department:
            self._capture_department = False
        if self._description_div_depth and tag in _BLOCK_TAGS:
            self.description_parts.append("\n")
        if self._description_div_depth and tag == "div":
            self._description_div_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self.title_parts.append(data)
        if self._capture_location:
            self.location_parts.append(data)
        if self._capture_department:
            self.department_parts.append(data)
        if self._description_div_depth:
            self.description_parts.append(data)


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != ATOMICWORK_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Atomicwork adapter requires adapter_key={ATOMICWORK_ADAPTER_KEY}."
        )
    if source.careers_url != ATOMICWORK_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Atomicwork adapter requires careers_url={ATOMICWORK_CAREERS_URL}."
        )


def _normalize_listing(source: CompanySource, row: _ListingRow) -> NormalizedJob:
    title = _required_text(row.title, "Atomicwork listing title")
    location = _required_text(row.location, "Atomicwork listing location")
    href = _required_text(row.href, "Atomicwork listing href")
    canonical_url, external_id = _canonical_detail_url(urljoin(ATOMICWORK_CAREERS_URL, href))
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=_normalize_text(title),
        location_original=location,
        location_normalized=_normalized_locations(location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": ATOMICWORK_ADAPTER_KEY,
            "department": row.department,
        },
    )


def _sitemap_job_urls(document: str) -> set[str]:
    if "<!DOCTYPE" in document.upper():
        raise ValueError("Atomicwork sitemap must not contain a document type declaration.")
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise ValueError("Atomicwork sitemap is not valid XML.") from error
    urls: set[str] = set()
    observed_detail_count = 0
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "loc" or element.text is None:
            continue
        value = element.text.strip()
        if not value:
            continue
        parsed = urlsplit(value)
        if _DETAIL_PATH_PATTERN.fullmatch(parsed.path) is None:
            continue
        observed_detail_count += 1
        canonical_url, _ = _canonical_detail_url(value)
        if canonical_url in urls:
            raise ValueError("Atomicwork sitemap contains a duplicate job-detail URL.")
        urls.add(canonical_url)
    if len(urls) != observed_detail_count:
        raise ValueError("Atomicwork sitemap job-detail inventory is incomplete.")
    return urls


def _canonical_detail_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    match = _DETAIL_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ATOMICWORK_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError(
            "Atomicwork job URL must be a same-origin HTTPS /careers/<id-or-slug> path."
        )
    external_id = match.group(1)
    return f"https://{ATOMICWORK_HOST}/careers/{external_id}", external_id


def _same_url(left: str, right: str) -> bool:
    return left.rstrip("/") == right.rstrip("/")


def _decode_utf8(
    body: bytes,
    context: str,
    diagnostics: list[AdapterDiagnostic],
) -> str | None:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        diagnostics.append(
            _diagnostic(
                "invalid_encoding",
                DiagnosticSeverity.ERROR,
                f"{context} was not valid UTF-8.",
            )
        )
        return None


def _plain_text(parts: list[str]) -> str | None:
    text = "".join(parts).replace("\r", "")
    text = re.sub(r"[ \t\f\v\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty.")
    return _normalize_whitespace(value)


def _optional_text(parts: list[str]) -> str | None:
    value = _compact_text(parts)
    return value or None


def _compact_text(parts: list[str]) -> str:
    return _normalize_whitespace(" ".join(parts))


def _compact_object_parts(value: object) -> str:
    return _compact_text(value) if isinstance(value, list) else ""


def _optional_object_parts(value: object) -> str | None:
    text = _compact_object_parts(value)
    return text or None


def _append_object_part(value: object, part: str) -> None:
    if isinstance(value, list):
        value.append(part)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text(value: str) -> str:
    return _normalize_whitespace(value).casefold()


def _normalized_locations(value: str) -> tuple[str, ...]:
    parts = tuple(_normalize_text(item) for item in re.split(r"[,|;/]", value) if item.strip())
    return parts or ("location unavailable",)


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
