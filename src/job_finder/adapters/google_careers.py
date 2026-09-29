"""Deterministic adapter for Google's public India careers search."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

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

GOOGLE_CAREERS_ADAPTER_KEY = "google_careers_india"
GOOGLE_CAREERS_URL = (
    "https://www.google.com/about/careers/applications/jobs/results/?location=India"
)
DEFAULT_PAGE_SIZE = 20
DEFAULT_MAX_PAGES = 100

_GOOGLE_HOST = "www.google.com"
_LISTING_PATH = "/about/careers/applications/jobs/results/"
_DETAIL_PATH_PATTERN = re.compile(
    r"/about/careers/applications/jobs/results/([0-9]+)-([a-z0-9][a-z0-9-]*)/?"
)
_BLOCK_TAGS = {"article", "div", "li", "ol", "p", "section", "ul"}
_SECTION_LABELS = {
    "minimum qualifications": "Minimum qualifications",
    "preferred qualifications": "Preferred qualifications",
    "about the job": "About the job",
    "responsibilities": "Responsibilities",
}


class GoogleCareersAdapter:
    """Retrieve Google's count-checked India inventory and deferred job details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = GOOGLE_CAREERS_ADAPTER_KEY

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
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None

        for page_number in range(1, self._max_pages + 1):
            page_url = _listing_url(page_number)
            try:
                response = self._client.get(
                    page_url,
                    accepted_content_types=("text/html",),
                    referer=GOOGLE_CAREERS_URL,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    page_number - 1,
                    diagnostics,
                )

            if not _is_listing_response(response.final_url, page_number):
                diagnostics.append(
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "Google Careers redirected outside the approved India search page.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_number,
                    diagnostics,
                )
            document = _decode_document(response.body)
            if document is None:
                diagnostics.append(
                    _diagnostic(
                        "invalid_encoding",
                        DiagnosticSeverity.ERROR,
                        "Google Careers listing was not valid UTF-8.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_number,
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
                    page_number,
                    diagnostics,
                )

            parser = _ListingParser()
            parser.feed(document)
            parser.close()
            if len(parser.total_counts) != 1:
                diagnostics.append(
                    _diagnostic(
                        "unsupported_schema",
                        DiagnosticSeverity.ERROR,
                        "Google Careers omitted a unique numeric jobs-matched count.",
                        page_number=page_number,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_number,
                    diagnostics,
                )
            observed_total = next(iter(parser.total_counts))
            if expected_total is None:
                expected_total = observed_total
            elif observed_total != expected_total:
                diagnostics.append(
                    _diagnostic(
                        "changing_total",
                        DiagnosticSeverity.ERROR,
                        "Google Careers total changed during pagination.",
                        expected_total=expected_total,
                        observed_total=observed_total,
                        page_number=page_number,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_number, diagnostics)

            remaining = expected_total - len(jobs)
            expected_page_count = min(self._page_size, max(remaining, 0))
            if len(parser.rows) != expected_page_count:
                diagnostics.append(
                    _diagnostic(
                        "declared_count_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Google Careers page size does not reconcile with its declared total.",
                        page_number=page_number,
                        expected_page_count=expected_page_count,
                        observed_page_count=len(parser.rows),
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_number, diagnostics)

            parse_errors = 0
            for job_index, row in enumerate(parser.rows):
                try:
                    job = _normalize_listing(source, row)
                except ValueError as error:
                    parse_errors += 1
                    diagnostics.append(
                        _diagnostic(
                            "malformed_job",
                            DiagnosticSeverity.ERROR,
                            str(error),
                            page_number=page_number,
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
                            "Google Careers returned a duplicate numeric job ID.",
                            page_number=page_number,
                            job_index=job_index,
                        )
                    )
                    return _result(
                        source, AdapterOutcome.SUSPICIOUS, jobs, page_number, diagnostics
                    )
                if external_id is not None:
                    seen_ids.add(external_id)
                jobs.append(job)
            if parse_errors:
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    page_number,
                    diagnostics,
                )

            if len(jobs) == expected_total:
                if jobs:
                    diagnostics.append(
                        _diagnostic(
                            "missing_publication_date",
                            DiagnosticSeverity.WARNING,
                            "Google Careers exposes no trustworthy job publication date.",
                            count=len(jobs),
                        )
                    )
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page_number,
                    diagnostics,
                    complete=True,
                )

        diagnostics.append(
            _diagnostic(
                "pagination_limit",
                DiagnosticSeverity.ERROR,
                "Google Careers pagination exceeded the configured page limit.",
                max_pages=self._max_pages,
                expected_total=expected_total if expected_total is not None else "unknown",
            )
        )
        return _result(source, AdapterOutcome.SUSPICIOUS, jobs, self._max_pages, diagnostics)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one official Google detail page without changing its identity."""
        _validate_source(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise DetailIdentityMismatch(
                "Google Careers detail job does not match the configured source."
            )
        canonical_url, external_id = _canonical_detail_url(job.canonical_url)
        if canonical_url != job.canonical_url or external_id != job.external_job_id:
            raise DetailIdentityMismatch(
                "Google Careers detail URL identity does not match the listing."
            )

        response = self._client.get(
            job.canonical_url,
            accepted_content_types=("text/html",),
            referer=GOOGLE_CAREERS_URL,
        )
        document = response.body.decode("utf-8")
        if is_access_block_html(document):
            raise HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
        response_url, response_id = _canonical_detail_url(response.final_url)
        if response_url != job.canonical_url or response_id != job.external_job_id:
            raise DetailIdentityMismatch(
                "Google Careers detail response URL does not match the listing."
            )

        parser = _DetailParser()
        parser.feed(document)
        parser.close()
        title = _required_text(_compact_text(parser.title_parts), "Google detail title")
        if _normalize_text(title) != job.title_normalized:
            raise DetailIdentityMismatch(
                "Google Careers detail title does not match the listing title."
            )
        locations = _unique_strings(_compact_text(parts) for parts in parser.location_parts)
        if not locations or not any(_is_india_location(value) for value in locations):
            raise DetailContentMissing("Google Careers detail must contain an India location.")

        sections: list[str] = []
        for key in (
            "minimum qualifications",
            "preferred qualifications",
            "about the job",
            "responsibilities",
        ):
            text = _section_text(parser.sections[key])
            if text:
                sections.append(f"{_SECTION_LABELS[key]}\n\n{text}")
            elif key != "preferred qualifications":
                raise DetailContentMissing(
                    f"Google Careers detail section {key} must be non-empty."
                )
        description = "\n\n".join(sections)
        metadata = dict(job.source_metadata)
        product = _clean_badge_text(parser.product_parts)
        experience = _clean_badge_text(parser.experience_parts)
        if product is not None:
            metadata["product"] = product
        if experience is not None:
            metadata["experience_level"] = experience
        return replace(
            job,
            title_original=title,
            title_normalized=_normalize_text(title),
            location_original=" | ".join(locations),
            location_normalized=_normalized_locations(" | ".join(locations)),
            published_at=None,
            published_at_raw=None,
            date_basis=DateBasis.UNKNOWN,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class _ListingRow:
    data_id: str | None
    title: str
    locations: tuple[str, ...]
    href: str | None
    product: str | None
    experience_level: str | None
    minimum_qualifications: str | None


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ListingRow] = []
        self.total_counts: set[int] = set()
        self._count_parts: list[str] | None = None
        self._card: dict[str, object] | None = None
        self._card_li_depth = 0
        self._capture_title = False
        self._capture_location = False
        self._capture_product = False
        self._capture_experience = False
        self._minimum_depth = 0
        self._icon_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "span" and "SWhIm" in classes:
            self._count_parts = []
        if tag == "li" and "lLd3Je" in classes and self._card is None:
            self._card = {
                "data_id": attributes.get("data-id"),
                "title": [],
                "locations": [],
                "href": None,
                "product": [],
                "experience": [],
                "minimum": [],
            }
            self._card_li_depth = 1
        elif self._card is not None and tag == "li":
            self._card_li_depth += 1
        if self._card is None:
            return
        if tag == "h3" and "QJPWVe" in classes:
            self._capture_title = True
        if tag == "span" and "r0wTof" in classes:
            self._capture_location = True
            _object_list(self._card, "locations").append([])
        if tag == "span" and "RP7SMd" in classes:
            self._capture_product = True
        if tag == "span" and "wVSTAb" in classes:
            self._capture_experience = True
        if tag == "div" and "Xsxa1e" in classes:
            self._minimum_depth = 1
        elif self._minimum_depth and tag == "div":
            self._minimum_depth += 1
        if self._minimum_depth and (tag in _BLOCK_TAGS or tag == "br"):
            _object_list(self._card, "minimum").append("\n")
        if tag == "i":
            self._icon_depth += 1
        if tag == "a":
            href = attributes.get("href")
            if isinstance(href, str) and _is_detail_href(href):
                existing = self._card.get("href")
                if existing is None:
                    self._card["href"] = href
                elif existing != href:
                    self._card["href"] = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._count_parts is not None:
            value = _compact_text(self._count_parts).replace(",", "")
            if value.isdigit():
                self.total_counts.add(int(value))
            self._count_parts = None
        if self._card is None:
            return
        if tag == "h3":
            self._capture_title = False
        if tag == "span":
            self._capture_location = False
            self._capture_product = False
            self._capture_experience = False
        if tag == "i" and self._icon_depth:
            self._icon_depth -= 1
        if self._minimum_depth and tag in _BLOCK_TAGS:
            _object_list(self._card, "minimum").append("\n")
        if self._minimum_depth and tag == "div":
            self._minimum_depth -= 1
        if tag != "li":
            return
        self._card_li_depth -= 1
        if self._card_li_depth != 0:
            return
        raw_locations = _object_list(self._card, "locations")
        locations = tuple(
            value
            for parts in raw_locations
            if isinstance(parts, list) and (value := _compact_object_parts(parts))
        )
        self.rows.append(
            _ListingRow(
                data_id=_optional_string(self._card.get("data_id")),
                title=_compact_object_parts(_object_list(self._card, "title")),
                locations=locations,
                href=_optional_string(self._card.get("href")),
                product=_clean_badge_text(
                    str(part) for part in _object_list(self._card, "product")
                ),
                experience_level=_clean_badge_text(
                    str(part) for part in _object_list(self._card, "experience")
                ),
                minimum_qualifications=_section_text(
                    str(part) for part in _object_list(self._card, "minimum")
                ),
            )
        )
        self._card = None
        self._capture_title = False
        self._capture_location = False
        self._capture_product = False
        self._capture_experience = False
        self._minimum_depth = 0

    def handle_data(self, data: str) -> None:
        if self._count_parts is not None:
            self._count_parts.append(data)
        if self._card is None or self._icon_depth:
            return
        if self._capture_title:
            _object_list(self._card, "title").append(data)
        if self._capture_location:
            locations = _object_list(self._card, "locations")
            if locations and isinstance(locations[-1], list):
                locations[-1].append(data)
        if self._capture_product:
            _object_list(self._card, "product").append(data)
        if self._capture_experience:
            _object_list(self._card, "experience").append(data)
        if self._minimum_depth:
            _object_list(self._card, "minimum").append(data)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.location_parts: list[list[str]] = []
        self.product_parts: list[str] = []
        self.experience_parts: list[str] = []
        self.sections: dict[str, list[str]] = {key: [] for key in _SECTION_LABELS}
        self._capture_title = False
        self._capture_location = False
        self._capture_product = False
        self._capture_experience = False
        self._heading_parts: list[str] | None = None
        self._active_section: str | None = None
        self._section_div_depth: int | None = None
        self._div_depth = 0
        self._icon_depth = 0
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div":
            self._div_depth += 1
        if tag in {"script", "style", "template"}:
            self._ignored_depth += 1
        if tag == "h2" and "p1N2lc" in classes and not self.title_parts:
            self._capture_title = True
        if tag == "h3":
            self._active_section = None
            self._section_div_depth = None
            self._heading_parts = []
        if self.title_parts and self._heading_parts is None:
            if tag == "span" and "r0wTof" in classes:
                self._capture_location = True
                self.location_parts.append([])
            if tag == "span" and "RP7SMd" in classes:
                self._capture_product = True
            if tag == "span" and "wVSTAb" in classes:
                self._capture_experience = True
        if tag == "i":
            self._icon_depth += 1
        if self._active_section is not None and (tag in _BLOCK_TAGS or tag == "br"):
            self.sections[self._active_section].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self._capture_title = False
        if tag == "h3" and self._heading_parts is not None:
            heading = _normalize_heading(_compact_text(self._heading_parts))
            self._active_section = heading if heading in _SECTION_LABELS else None
            if self._active_section is not None:
                self._section_div_depth = self._div_depth
            self._heading_parts = None
        if tag == "span":
            self._capture_location = False
            self._capture_product = False
            self._capture_experience = False
        if tag == "i" and self._icon_depth:
            self._icon_depth -= 1
        if self._active_section is not None and tag in _BLOCK_TAGS:
            self.sections[self._active_section].append("\n")
        if tag == "div":
            if self._active_section is not None and self._section_div_depth == self._div_depth:
                self._active_section = None
                self._section_div_depth = None
            self._div_depth -= 1
        if tag in {"script", "style", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._icon_depth or self._ignored_depth:
            return
        if self._capture_title:
            self.title_parts.append(data)
        if self._heading_parts is not None:
            self._heading_parts.append(data)
            return
        if self._capture_location and self.location_parts:
            self.location_parts[-1].append(data)
        if self._capture_product:
            self.product_parts.append(data)
        if self._capture_experience:
            self.experience_parts.append(data)
        if self._active_section is not None:
            self.sections[self._active_section].append(data)


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != GOOGLE_CAREERS_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Google Careers adapter requires adapter_key={GOOGLE_CAREERS_ADAPTER_KEY}."
        )
    if source.careers_url != GOOGLE_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Google Careers adapter requires careers_url={GOOGLE_CAREERS_URL}."
        )


def _listing_url(page_number: int) -> str:
    return GOOGLE_CAREERS_URL if page_number == 1 else f"{GOOGLE_CAREERS_URL}&page={page_number}"


def _is_listing_response(url: str, page_number: int) -> bool:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    observed_page = query.get("page", ["1"])
    return (
        parsed.scheme == "https"
        and parsed.hostname == _GOOGLE_HOST
        and parsed.port is None
        and parsed.path == _LISTING_PATH
        and query.get("location") == ["India"]
        and observed_page == [str(page_number)]
    )


def _normalize_listing(source: CompanySource, row: _ListingRow) -> NormalizedJob:
    title = _required_text(row.title, "Google listing title")
    locations = _unique_strings(row.locations)
    if not locations:
        raise ValueError("Google Careers listing must contain a location.")
    href = _required_text(row.href, "Google listing href")
    canonical_url, external_id = _canonical_detail_url(
        urljoin("https://www.google.com/about/careers/applications/", href)
    )
    data_id = _optional_string(row.data_id)
    if data_id is not None and data_id != external_id:
        raise ValueError("Google Careers listing data-id does not match its job URL.")
    location = " | ".join(locations)
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
            "adapter_key": GOOGLE_CAREERS_ADAPTER_KEY,
            "product": row.product,
            "experience_level": row.experience_level,
            "listing_minimum_qualifications": row.minimum_qualifications,
            "india_search_result": True,
        },
    )


def _canonical_detail_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    match = _DETAIL_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _GOOGLE_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or match is None
    ):
        raise ValueError("Google job URL must be an official numeric job-detail path.")
    return f"https://{_GOOGLE_HOST}{parsed.path.rstrip('/')}", match.group(1)


def _is_detail_href(value: str) -> bool:
    try:
        _canonical_detail_url(urljoin("https://www.google.com/about/careers/applications/", value))
    except ValueError:
        return False
    return True


def _decode_document(body: bytes) -> str | None:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _is_india_location(value: str) -> bool:
    return "india" in {part.strip().casefold() for part in re.split(r"[,|;/]", value)}


def _normalize_heading(value: str) -> str:
    return value.rstrip(":").strip().casefold()


def _section_text(parts: Iterable[str]) -> str | None:
    text = "".join(parts).replace("\r", "")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    normalized = "\n".join(line for line in lines if line)
    return normalized or None


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty.")
    return re.sub(r"\s+", " ", value).strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_badge_text(parts: Iterable[str]) -> str | None:
    value = _compact_text(parts)
    return value or None


def _compact_text(parts: Iterable[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _object_list(value: dict[str, object], key: str) -> list[object]:
    result = value[key]
    if not isinstance(result, list):
        raise TypeError(f"internal parser field {key} must be a list")
    return result


def _compact_object_parts(parts: list[object]) -> str:
    return _compact_text(str(part) for part in parts)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalized_locations(value: str) -> tuple[str, ...]:
    return tuple(
        _unique_strings(
            _normalize_text(piece) for piece in re.split(r"[,|;/]", value) if piece.strip()
        )
    )


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
