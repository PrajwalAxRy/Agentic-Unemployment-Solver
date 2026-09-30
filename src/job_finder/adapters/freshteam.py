"""Adapter for Freshteam's public career portals."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
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

_ACCOUNT_PATTERN = re.compile(r"[A-Za-z0-9-]+")
_JOB_PATH_PATTERN = re.compile(r"/jobs/([A-Za-z0-9_-]+)/([^/?#]+)/?")
_DECLARED_COUNT_PATTERN = re.compile(r"#(\d+)\s+Jobs?\b", re.IGNORECASE)
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


class FreshteamAdapter:
    """Retrieve a complete Freshteam board and its schema.org job details."""

    adapter_type = AdapterType.FRESHTEAM

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        account = _account(source)
        diagnostics: list[AdapterDiagnostic] = []
        endpoint = _listing_endpoint(account)
        try:
            response = self._client.get(
                endpoint,
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
                    "Freshteam response was not valid UTF-8 HTML.",
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
        if not _is_expected_response_url(response.final_url, account, listing=True):
            diagnostics.append(
                diagnostic(
                    "unexpected_redirect",
                    DiagnosticSeverity.ERROR,
                    "Freshteam listing redirected outside the configured public board.",
                )
            )
            return _result(source, AdapterOutcome.FAILED, [], diagnostics)

        parser = _ListingParser(account)
        parser.feed(document)
        parser.close()
        if parser.declared_count is None:
            diagnostics.append(
                diagnostic(
                    "missing_declared_count",
                    DiagnosticSeverity.ERROR,
                    "Freshteam page did not declare its public job count.",
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, [], diagnostics)
        if parser.declared_count != len(parser.rows):
            diagnostics.append(
                diagnostic(
                    "declared_count_mismatch",
                    DiagnosticSeverity.ERROR,
                    "Freshteam's declared job count did not match parsed job cards.",
                    declared_count=parser.declared_count,
                    parsed_count=len(parser.rows),
                )
            )
            return _result(source, AdapterOutcome.SUSPICIOUS, [], diagnostics)
        if parser.declared_count == 0:
            return _result(source, AdapterOutcome.EMPTY, [], diagnostics, complete=True)

        jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()
        parse_error_count = 0
        for job_index, row in enumerate(parser.rows):
            try:
                job = _normalize_listing(source, account, row)
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
                        "Freshteam returned a duplicate job ID.",
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
                "publication_date_requires_detail",
                DiagnosticSeverity.INFO,
                "Freshteam detail pages provide datePosted and full descriptions.",
                count=len(jobs),
            )
        )
        return _result(source, AdapterOutcome.SUCCESS, jobs, diagnostics, complete=True)

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one public Freshteam JSON-LD detail without changing identity."""
        account = _account(source)
        if job.company_id != source.company_id or job.source_type != self.adapter_type.value:
            raise ValueError("Freshteam detail job does not match the configured source.")
        if job.external_job_id is None:
            raise ValueError("Freshteam detail retrieval requires an external job ID.")
        _validate_job_url(job.canonical_url, account, job.external_job_id)
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
            account,
            listing=False,
            external_id=job.external_job_id,
        ):
            raise ValueError("Freshteam detail response URL does not match the listing.")

        parser = _JsonLdParser()
        parser.feed(document)
        parser.close()
        posting = _job_posting(parser.documents)
        detail_url = clean_optional(posting.get("url"))
        if detail_url is not None:
            _validate_job_url(detail_url, account, job.external_job_id)
        title = required_string(posting, "title", "Freshteam detail")
        published_raw = clean_optional(posting.get("datePosted"))
        published_at = _parse_timestamp(published_raw)
        description_html = clean_optional(posting.get("description"))
        description = _plain_text(html.unescape(description_html)) if description_html else None
        detail_location = _job_location(posting.get("jobLocation"))
        remote = posting.get("remote") is True or job.source_metadata.get("remote") is True
        location = detail_location or job.location_original
        if remote and "remote" not in location.casefold():
            location = f"{location}, Remote"
        metadata = dict(job.source_metadata)
        metadata.update(
            {
                "datePosted": published_raw,
                "employment_type": posting.get("employmentType"),
                "remote": remote,
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
    location: str
    href: str
    job_type: str | None
    remote: bool


class _ListingParser(HTMLParser):
    def __init__(self, account: str) -> None:
        super().__init__(convert_charrefs=True)
        self.account = account
        self.rows: list[_ListingRow] = []
        self.declared_count: int | None = None
        self._row: dict[str, object] | None = None
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta" and (attributes.get("property") or "").casefold() == "og:description":
            match = _DECLARED_COUNT_PATTERN.search(attributes.get("content") or "")
            if match is not None:
                self.declared_count = int(match.group(1))
        classes = set((attributes.get("class") or "").split())
        href = attributes.get("href")
        if (
            tag == "a"
            and "heading" in classes
            and isinstance(href, str)
            and _is_listing_href(href, self.account)
        ):
            self._row = {
                "title": [],
                "location": attributes.get("data-portal-location") or "",
                "href": href,
                "job_type": attributes.get("data-portal-job-type"),
                "remote": (attributes.get("data-portal-remote-location") or "").casefold()
                == "true",
            }
        if self._row is not None and "job-title" in classes:
            self._capture_title = True

    def handle_endtag(self, tag: str) -> None:
        if self._row is None:
            return
        if tag == "div" and self._capture_title:
            self._capture_title = False
        elif tag == "a":
            title_parts = self._row["title"]
            self.rows.append(
                _ListingRow(
                    title=_compact_text(title_parts if isinstance(title_parts, list) else []),
                    location=(
                        self._row["location"] if isinstance(self._row["location"], str) else ""
                    ),
                    href=self._row["href"] if isinstance(self._row["href"], str) else "",
                    job_type=(
                        self._row["job_type"] if isinstance(self._row["job_type"], str) else None
                    ),
                    remote=self._row["remote"] is True,
                )
            )
            self._row = None
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        if self._row is not None and self._capture_title:
            title_parts = self._row["title"]
            if isinstance(title_parts, list):
                title_parts.append(data)


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


def _account(source: CompanySource) -> str:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.FRESHTEAM,
        required_parameters=("account",),
    )
    account = parameters["account"].strip()
    if not _ACCOUNT_PATTERN.fullmatch(account):
        raise ValueError("Freshteam account must contain only letters, digits, and hyphens.")
    return account


def _listing_endpoint(account: str) -> str:
    return f"https://{account}.freshteam.com/jobs"


def _is_listing_href(href: str, account: str) -> bool:
    parsed = urlsplit(urljoin(_listing_endpoint(account), href))
    return (
        parsed.scheme == "https"
        and parsed.hostname == f"{account}.freshteam.com"
        and _JOB_PATH_PATTERN.fullmatch(parsed.path) is not None
    )


def _normalize_listing(
    source: CompanySource,
    account: str,
    row: _ListingRow,
) -> NormalizedJob:
    title = _required_text(row.title, "Freshteam listing title")
    location = _required_text(row.location, "Freshteam listing location")
    canonical_url = _canonical_job_url(row.href, account)
    external_id = _job_id(canonical_url, account)
    if row.remote and "remote" not in location.casefold():
        location = f"{location}, Remote"
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.FRESHTEAM.value,
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
        source_metadata={"job_type": row.job_type, "remote": row.remote},
    )


def _canonical_job_url(value: str, account: str) -> str:
    parsed = urlsplit(urljoin(_listing_endpoint(account), value))
    if (
        parsed.scheme != "https"
        or parsed.hostname != f"{account}.freshteam.com"
        or _JOB_PATH_PATTERN.fullmatch(parsed.path) is None
    ):
        raise ValueError("Freshteam job URL must use the configured public account and job ID.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _job_id(url: str, account: str) -> str:
    parsed = urlsplit(url)
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != f"{account}.freshteam.com" or match is None:
        raise ValueError("Freshteam job URL must use the configured public account and job ID.")
    return match.group(1)


def _validate_job_url(url: str, account: str, external_id: str) -> None:
    if _job_id(url, account) != external_id:
        raise ValueError("Freshteam detail URL job ID does not match the listing.")


def _is_expected_response_url(
    url: str,
    account: str,
    *,
    listing: bool,
    external_id: str | None = None,
) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != f"{account}.freshteam.com":
        return False
    if listing:
        return parsed.path.rstrip("/") == "/jobs"
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    return match is not None and (external_id is None or match.group(1) == external_id)


def _job_posting(documents: Iterable[object]) -> Mapping[object, object]:
    for document in documents:
        candidates: list[object] = []
        if isinstance(document, Mapping):
            candidates.append(document)
            graph = document.get("@graph")
            if isinstance(graph, list):
                candidates.extend(graph)
        elif isinstance(document, list):
            candidates.extend(document)
        for candidate in candidates:
            if isinstance(candidate, Mapping) and candidate.get("@type") == "JobPosting":
                return candidate
    raise ValueError("Freshteam detail did not contain JobPosting JSON-LD.")


def _job_location(value: object) -> str | None:
    locations = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for location in locations:
        if not isinstance(location, Mapping):
            continue
        address = location.get("address")
        if not isinstance(address, Mapping):
            continue
        for key in ("addressLocality", "addressRegion", "addressCountry"):
            item = clean_optional(address.get(key))
            if item is not None:
                parts.append(item)
    unique = unique_strings(parts)
    return ", ".join(unique) if unique else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    if value.endswith(" UTC"):
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _required_text(value: str | None, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string.")
    return value.strip()


def _compact_text(parts: Iterable[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


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
