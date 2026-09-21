"""Adapter for Jobvite's public desktop careers pages."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

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

JOBVITE_HOST = "jobs.jobvite.com"
_COMPANY_PATTERN = re.compile(r"[A-Za-z0-9-]+")
_JOB_PATH_PATTERN = re.compile(r"/([A-Za-z0-9-]+)/job/([A-Za-z0-9_-]+)/?$")
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


class JobviteAdapter:
    """Retrieve one complete public Jobvite board and optional job details."""

    adapter_type = AdapterType.JOBVITE

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        company = _company(source)
        diagnostics: list[AdapterDiagnostic] = []
        try:
            response = self._client.get(
                _listing_endpoint(company),
                accepted_content_types=("text/html",),
                referer=source.careers_url,
            )
        except HttpRequestError as error:
            diagnostics.append(request_failure_diagnostic(error))
            return _result(source, _request_outcome(error), [], diagnostics)
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError:
            diagnostics.append(
                _diagnostic(
                    "invalid_html",
                    DiagnosticSeverity.ERROR,
                    "Jobvite response was not valid UTF-8 HTML.",
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
        if not _is_expected_response_url(response.final_url, company, listing=True):
            diagnostics.append(
                _diagnostic(
                    "unexpected_redirect",
                    DiagnosticSeverity.ERROR,
                    "Jobvite listing redirected outside the configured public board.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)

        parser = _ListingParser(company)
        parser.feed(document)
        parser.close()
        if not parser.is_job_page or not parser.has_open_positions_heading:
            diagnostics.append(
                _diagnostic(
                    "unsupported_schema",
                    DiagnosticSeverity.ERROR,
                    "Jobvite response did not contain the public jobs-page markers.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)
        if parser.has_pagination:
            diagnostics.append(
                _diagnostic(
                    "unexpected_pagination",
                    DiagnosticSeverity.ERROR,
                    "Jobvite exposed pagination that this complete-board adapter cannot verify.",
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, [], diagnostics)
        if not parser.rows:
            error_text = _compact_text(parser.page_error_parts)
            if "no open positions" in error_text.casefold() or "no jobs" in error_text.casefold():
                return _result(source, AdapterOutcome.EMPTY, [], diagnostics, complete=True)
            diagnostics.append(
                _diagnostic(
                    "unexplained_empty_page",
                    DiagnosticSeverity.ERROR,
                    "Jobvite returned no jobs without an explicit empty-board message.",
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, [], diagnostics)

        jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()
        parse_error_count = 0
        for job_index, row in enumerate(parser.rows):
            try:
                job = _normalize_listing(source, company, row)
            except ValueError as error:
                parse_error_count += 1
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
                        "Jobvite returned a duplicate job ID.",
                        job_index=job_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, diagnostics)
            if job.external_job_id is not None:
                seen_ids.add(job.external_job_id)
            jobs.append(job)

        if parse_error_count:
            return _result(
                source,
                AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                jobs,
                diagnostics,
            )
        diagnostics.append(
            _diagnostic(
                "missing_publication_date",
                DiagnosticSeverity.WARNING,
                "Jobvite listing pages omit datePosted; detail retrieval supplies it.",
                count=len(jobs),
            )
        )
        return _result(source, AdapterOutcome.SUCCESS, jobs, diagnostics, complete=True)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one public Jobvite JSON-LD detail without changing identity."""
        company = _company(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Jobvite detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("Jobvite detail retrieval requires an external job ID.")
        _validate_job_url(job.canonical_url, company, job.external_job_id)
        endpoint = job.canonical_url + "?" + urlencode({"nl": "1"})
        response = self._client.get(
            endpoint,
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
            company,
            listing=False,
            external_id=job.external_job_id,
        ):
            raise ValueError("Jobvite detail response URL does not match the listing.")

        parser = _JsonLdParser()
        parser.feed(document)
        parser.close()
        posting = _job_posting(parser.documents)
        title = _required_string(posting, "title", "Jobvite detail")
        published_raw = _optional_string(posting.get("datePosted"))
        published_at = _parse_date(published_raw)
        description_html = _optional_string(posting.get("description"))
        description = _plain_text(description_html) if description_html is not None else None
        detail_location = _job_location(posting.get("jobLocation"))
        location = detail_location or job.location_original
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
            title_normalized=_normalize_text(title),
            location_original=location,
            location_normalized=_normalized_locations(location),
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
    location: str
    href: str | None


class _ListingParser(HTMLParser):
    def __init__(self, company: str) -> None:
        super().__init__(convert_charrefs=True)
        self.company = company
        self.rows: list[_ListingRow] = []
        self.is_job_page = False
        self.has_open_positions_heading = False
        self.has_pagination = False
        self.page_error_parts: list[str] = []
        self._row: dict[str, object] | None = None
        self._capture_name = False
        self._capture_location = False
        self._capture_heading = False
        self._heading_parts: list[str] = []
        self._capture_page_error = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "body" and "jv-page-jobs" in classes:
            self.is_job_page = True
        if (
            any("pagination" in item.casefold() for item in classes)
            or attributes.get("rel") == "next"
        ):
            self.has_pagination = True
        if tag in {"h1", "h2", "h3"} and "listing-header" in classes:
            self._capture_heading = True
            self._heading_parts = []
        if "jv-page-error" in classes:
            self._capture_page_error = True
        href = attributes.get("href")
        if tag == "a" and isinstance(href, str) and _is_listing_href(href, self.company):
            self._row = {"title": [], "location": [], "href": href}
        if self._row is not None and "jv-job-list-name" in classes:
            self._capture_name = True
        if self._row is not None and "jv-job-list-location" in classes:
            self._capture_location = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"} and self._capture_heading:
            heading = _compact_text(self._heading_parts)
            self.has_open_positions_heading = heading.casefold() == "open positions"
            self._capture_heading = False
        if tag == "div" and self._capture_page_error:
            self._capture_page_error = False
        if self._row is None:
            return
        if tag == "div" and self._capture_name:
            self._capture_name = False
        elif tag == "div" and self._capture_location:
            self._capture_location = False
        elif tag == "a":
            self.rows.append(
                _ListingRow(
                    title=_compact_text(self._row["title"]),  # type: ignore[arg-type]
                    location=_compact_text(self._row["location"]),  # type: ignore[arg-type]
                    href=self._row["href"] if isinstance(self._row["href"], str) else None,
                )
            )
            self._row = None
            self._capture_name = False
            self._capture_location = False

    def handle_data(self, data: str) -> None:
        if self._capture_heading:
            self._heading_parts.append(data)
        if self._capture_page_error:
            self.page_error_parts.append(data)
        if self._row is not None and self._capture_name:
            title = self._row["title"]
            if isinstance(title, list):
                title.append(data)
        if self._row is not None and self._capture_location:
            location = self._row["location"]
            if isinstance(location, list):
                location.append(data)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.documents: list[object] = []
        self._capture = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and (attributes.get("type") or "").casefold() == "application/ld+json":
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


def _company(source: CompanySource) -> str:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.JOBVITE,
        required_parameters=("company",),
    )
    company = parameters["company"].strip()
    if not _COMPANY_PATTERN.fullmatch(company):
        raise ValueError("Jobvite company must contain only letters, digits, and hyphens.")
    return company


def _listing_endpoint(company: str) -> str:
    return f"https://{JOBVITE_HOST}/{company}/jobs?" + urlencode({"nl": "1"})


def _is_listing_href(href: str, company: str) -> bool:
    parsed = urlsplit(urljoin(f"https://{JOBVITE_HOST}/", href))
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    return (
        parsed.hostname == JOBVITE_HOST
        and match is not None
        and match.group(1).casefold() == company.casefold()
    )


def _normalize_listing(
    source: CompanySource,
    company: str,
    row: _ListingRow,
) -> NormalizedJob:
    title = _required_text(row.title, "Jobvite listing title")
    location = _required_text(row.location, "Jobvite listing location")
    href = _required_text(row.href, "Jobvite listing href")
    canonical_url = urljoin(f"https://{JOBVITE_HOST}/", href)
    external_id = _job_id(canonical_url, company)
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.JOBVITE.value,
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
        source_metadata={},
    )


def _job_id(url: str, company: str) -> str:
    parsed = urlsplit(url)
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != JOBVITE_HOST
        or match is None
        or match.group(1).casefold() != company.casefold()
    ):
        raise ValueError("Jobvite job URL must use the configured public board and job ID.")
    return match.group(2)


def _validate_job_url(url: str, company: str, external_id: str) -> None:
    if _job_id(url, company) != external_id:
        raise ValueError("Jobvite detail URL job ID does not match the listing.")


def _is_expected_response_url(
    url: str,
    company: str,
    *,
    listing: bool,
    external_id: str | None = None,
) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != JOBVITE_HOST:
        return False
    if listing:
        return parsed.path.rstrip("/").casefold() == f"/{company}/jobs".casefold()
    return external_id is not None and _job_id(url, company) == external_id


def _job_posting(documents: Iterable[object]) -> Mapping[object, object]:
    for document in documents:
        result = _find_job_posting(document)
        if result is not None:
            return result
    raise ValueError("Jobvite detail response requires valid JobPosting JSON-LD.")


def _find_job_posting(value: object) -> Mapping[object, object] | None:
    if isinstance(value, Mapping):
        item_type = value.get("@type")
        if item_type == "JobPosting" or (isinstance(item_type, list) and "JobPosting" in item_type):
            return value
        for child in value.values():
            result = _find_job_posting(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_job_posting(child)
            if result is not None:
                return result
    return None


def _job_location(value: object) -> str | None:
    places = value if isinstance(value, list) else [value]
    components: list[str] = []
    for place in places:
        if not isinstance(place, Mapping):
            continue
        address = place.get("address")
        if not isinstance(address, Mapping):
            continue
        country = address.get("addressCountry")
        if isinstance(country, Mapping):
            country = country.get("name")
        for component in (
            address.get("streetAddress"),
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("postalCode"),
            country,
        ):
            text = _optional_string(component)
            if text is not None and text.casefold() not in {item.casefold() for item in components}:
                components.append(text)
    return ", ".join(components) or None


def _plain_text(value: str) -> str | None:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts).replace("\r", "")
    text = re.sub(r"[ \t\f\v\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _required_string(raw: Mapping[object, object], key: str, context: str) -> str:
    value = _optional_string(raw.get(key))
    if value is None:
        raise ValueError(f"{context} field {key} must be a non-empty string.")
    return value


def _required_text(value: object, field: str) -> str:
    text = _optional_string(value)
    if text is None:
        raise ValueError(f"{field} must be non-empty.")
    return text


def _optional_string(value: object) -> str | None:
    return _normalize_whitespace(value) if isinstance(value, str) and value.strip() else None


def _compact_text(parts: list[str]) -> str:
    return _normalize_whitespace(" ".join(parts))


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
