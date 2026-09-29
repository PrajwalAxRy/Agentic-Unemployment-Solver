"""Deterministic adapter for Index Exchange's official careers inventory."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser
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
from job_finder.normalization.jobs import normalize_source_locations as _shared_locations
from job_finder.normalization.jobs import normalize_title

_WHITESPACE_RUN = re.compile(r"\s+")

INDEX_EXCHANGE_ADAPTER_KEY = "index_exchange_official_inventory"
INDEX_EXCHANGE_CAREERS_URL = "https://www.indexexchange.com/careers/opportunities/"

_DETAIL_HOST = "jobs.gem.com"
_DETAIL_PATH = re.compile(r"/index-exchange/([A-Za-z0-9_-]+)")


@dataclass(frozen=True, slots=True)
class _ListingRow:
    external_id: str
    title: str
    location: str
    department: str
    canonical_url: str


class IndexExchangeCareersAdapter:
    """Read the complete official table and defer Gem-hosted descriptions."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = INDEX_EXCHANGE_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                INDEX_EXCHANGE_CAREERS_URL,
                accepted_content_types=("text/html",),
                referer=INDEX_EXCHANGE_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url.rstrip("/") != INDEX_EXCHANGE_CAREERS_URL.rstrip("/"):
            return _failed(source, "unexpected_redirect", "Careers inventory redirected.")
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError:
            return _failed(source, "invalid_encoding", "Careers inventory was not valid UTF-8.")
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
                [request_failure_diagnostic(block_error)],
                page_count=1,
            )

        parser = _ListingParser()
        try:
            parser.feed(document)
            parser.close()
            rows = parser.validated_rows()
            jobs = _collapse_rows(source, rows)
        except ValueError as error:
            return _failed(source, "unsupported_schema", str(error))

        diagnostics = [
            _diagnostic(
                "missing_publication_date",
                DiagnosticSeverity.WARNING,
                "Index Exchange exposes no verified publication date in its official inventory.",
                count=len(jobs),
            )
        ]
        return _result(
            source,
            AdapterOutcome.SUCCESS,
            jobs,
            diagnostics,
            page_count=1,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        _validate_source(source)
        _validate_job(source, job)
        try:
            response = self._client.get(
                job.canonical_url,
                accepted_content_types=("text/html",),
                referer=INDEX_EXCHANGE_CAREERS_URL,
            )
        except HttpRequestError as error:
            raise DetailContentMissing(
                f"Index Exchange detail request failed: {error.category.value}"
            ) from error
        if response.final_url != job.canonical_url:
            raise DetailIdentityMismatch(
                "Index Exchange detail redirected outside its canonical URL."
            )
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DetailContentMissing("Index Exchange detail was not valid UTF-8.") from error
        if is_access_block_html(document):
            raise DetailContentMissing("Index Exchange detail returned an access-control page.")
        parser = _DetailMetaParser()
        parser.feed(document)
        parser.close()
        title = parser.required("og:title")
        canonical_url = parser.required("og:url")
        description = _normalize_whitespace(parser.required("og:description"))
        if normalize_title(title) != job.title_normalized:
            raise DetailIdentityMismatch("Index Exchange detail title did not match the listing.")
        if canonical_url != job.canonical_url:
            raise DetailIdentityMismatch(
                "Index Exchange detail canonical URL did not match the listing."
            )
        if len(description) < 80:
            raise DetailContentMissing("Index Exchange detail description was insufficient.")
        return replace(
            job,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata={**job.source_metadata, "detail_retrieved": True},
        )


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ListingRow] = []
        self.expected_row_count: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value for key, value in attrs}
        classes = (attributes.get("class") or "").split()
        if tag.casefold() == "tr" and "table-item" in classes:
            self.rows.append(_row_from_attributes(attributes))
        if tag.casefold() == "ul" and "pagination" in classes:
            raw_count = attributes.get("data-count")
            if raw_count is None or not raw_count.isdigit():
                raise ValueError("Index Exchange pagination omitted a numeric row count.")
            observed = int(raw_count)
            if self.expected_row_count is not None and self.expected_row_count != observed:
                raise ValueError("Index Exchange exposed conflicting pagination counts.")
            self.expected_row_count = observed

    def validated_rows(self) -> list[_ListingRow]:
        if self.expected_row_count is None:
            raise ValueError("Index Exchange inventory omitted its pagination contract.")
        if self.expected_row_count <= 0:
            raise ValueError("Index Exchange has no independently proved empty-state contract.")
        if len(self.rows) != self.expected_row_count:
            raise ValueError("Index Exchange row count did not match its pagination contract.")
        return self.rows


class _DetailMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        attributes = {key.casefold(): value for key, value in attrs}
        key = attributes.get("property")
        value = attributes.get("content")
        if key in {"og:title", "og:url", "og:description"} and value is not None:
            if key in self.values and self.values[key] != value:
                raise ValueError(f"Index Exchange detail exposed conflicting {key} values.")
            self.values[key] = value

    def required(self, key: str) -> str:
        value = self.values.get(key)
        if value is None or not value.strip():
            raise ValueError(f"Index Exchange detail omitted {key}.")
        return value.strip()


def _row_from_attributes(attributes: dict[str, str | None]) -> _ListingRow:
    required = {
        name: attributes.get(name)
        for name in (
            "data-list-item-id",
            "data-list-item-title",
            "data-list-item-location",
            "data-list-department-name",
            "data-url",
        )
    }
    if any(value is None or not value.strip() for value in required.values()):
        raise ValueError("Index Exchange inventory row omitted a required data attribute.")
    external_id = required["data-list-item-id"]
    title = required["data-list-item-title"]
    location = required["data-list-item-location"]
    department = required["data-list-department-name"]
    canonical_url = required["data-url"]
    assert external_id is not None
    assert title is not None
    assert location is not None
    assert department is not None
    assert canonical_url is not None
    if _external_id(canonical_url) != external_id:
        raise ValueError("Index Exchange row ID and Gem URL did not agree.")
    return _ListingRow(
        external_id,
        _normalize_whitespace(title),
        _normalize_whitespace(location),
        _normalize_whitespace(department),
        canonical_url,
    )


def _collapse_rows(source: CompanySource, rows: list[_ListingRow]) -> list[NormalizedJob]:
    by_id: dict[str, _ListingRow] = {}
    locations: dict[str, list[str]] = {}
    for row in rows:
        previous = by_id.get(row.external_id)
        if previous is not None and (
            previous.title != row.title
            or previous.department != row.department
            or previous.canonical_url != row.canonical_url
        ):
            raise ValueError("Index Exchange duplicate ID had conflicting job metadata.")
        by_id.setdefault(row.external_id, row)
        job_locations = locations.setdefault(row.external_id, [])
        if row.location.casefold() not in {value.casefold() for value in job_locations}:
            job_locations.append(row.location)

    return [
        NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=AdapterType.CUSTOM.value,
            external_job_id=row.external_id,
            title_original=row.title,
            title_normalized=normalize_title(row.title),
            location_original=" | ".join(locations[row.external_id]),
            location_normalized=_shared_locations(locations[row.external_id]),
            published_at=None,
            published_at_raw=None,
            date_basis=DateBasis.UNKNOWN,
            canonical_url=row.canonical_url,
            description=None,
            description_hash=None,
            source_metadata={
                "adapter_key": INDEX_EXCHANGE_ADAPTER_KEY,
                "department": row.department,
                "listing_row_count": len(rows),
            },
        )
        for row in by_id.values()
    ]


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != INDEX_EXCHANGE_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Index Exchange adapter requires adapter_key={INDEX_EXCHANGE_ADAPTER_KEY}."
        )
    if source.careers_url != INDEX_EXCHANGE_CAREERS_URL:
        raise AdapterConfigurationError("Index Exchange adapter requires the approved careers URL.")


def _validate_job(source: CompanySource, job: NormalizedJob) -> None:
    if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
        raise AdapterConfigurationError("Index Exchange detail job does not belong to the source.")
    if job.external_job_id is None or _external_id(job.canonical_url) != job.external_job_id:
        raise AdapterConfigurationError("Index Exchange detail job identity is inconsistent.")


def _external_id(url: str) -> str:
    parsed = urlsplit(url)
    match = _DETAIL_PATH.fullmatch(parsed.path.rstrip("/"))
    if (
        parsed.scheme != "https"
        or parsed.hostname != _DETAIL_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("Index Exchange row used an unexpected Gem URL.")
    return match.group(1)


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


def _failed(source: CompanySource, category: str, message: str) -> AdapterResult:
    return _result(
        source,
        AdapterOutcome.FAILED,
        [],
        [_diagnostic(category, DiagnosticSeverity.ERROR, message)],
        page_count=1,
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
