"""Deterministic adapter for Aganitha's public careers index and detail pages."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import urlsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
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

AGANITHA_ADAPTER_KEY = "aganitha_careers_index"
AGANITHA_CAREERS_URL = "https://www.aganitha.ai/careers/"

_HOST = "www.aganitha.ai"
_DETAIL_PATH_PATTERN = re.compile(r"/careers/([a-z0-9]+(?:-[a-z0-9]+)*)/")
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
    "main",
    "ol",
    "p",
    "section",
    "ul",
}
_SKIP_TAGS = {"script", "style", "svg", "noscript"}


@dataclass(frozen=True, slots=True)
class _ListingRow:
    title: str
    canonical_url: str
    external_id: str


@dataclass(frozen=True, slots=True)
class _DetailData:
    title: str
    location: str
    description: str | None


class AganithaCareersAdapter:
    """Read the official accordion inventory and defer full job-description parsing."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = AGANITHA_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                AGANITHA_CAREERS_URL,
                accepted_content_types=("text/html",),
                referer=AGANITHA_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url.rstrip("/") != AGANITHA_CAREERS_URL.rstrip("/"):
            return _failed(
                source,
                "unexpected_redirect",
                "Aganitha careers index redirected outside the approved page.",
                page_count=1,
            )
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError:
            return _failed(
                source,
                "invalid_encoding",
                "Aganitha careers index was not valid UTF-8.",
                page_count=1,
            )
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

        try:
            rows = _listing_rows(document)
        except ValueError as error:
            return _failed(source, "unsupported_schema", str(error), page_count=1)
        if not rows:
            return _failed(
                source,
                "unproved_empty_inventory",
                "Aganitha index exposed no independently proved empty-state contract.",
                page_count=1,
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        page_count = 1
        seen_ids: set[str] = set()
        for index, row in enumerate(rows):
            if row.external_id in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Aganitha returned a duplicate job slug.",
                        job_index=index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    diagnostics,
                    page_count=page_count,
                )
            seen_ids.add(row.external_id)
            try:
                detail = self._fetch_detail(row.canonical_url, include_description=False)
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "metadata_detail_failure",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_count=page_count,
                )
            page_count += 1
            if not _titles_compatible(detail.title, row.title):
                diagnostics.append(
                    _diagnostic(
                        "title_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Aganitha listing and detail titles did not match.",
                        job_index=index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_count=page_count,
                )
            if _normalize_text(detail.title) != _normalize_text(row.title):
                diagnostics.append(
                    _diagnostic(
                        "title_variation_normalized",
                        DiagnosticSeverity.INFO,
                        "Aganitha listing and detail titles differ only by compatible wording.",
                        job_index=index,
                    )
                )
            jobs.append(_normalized_job(source, row, detail))

        diagnostics.append(
            _diagnostic(
                "missing_publication_date",
                DiagnosticSeverity.WARNING,
                "Aganitha's job inventory exposes no verified job-publication date.",
                count=len(jobs),
            )
        )
        return _result(
            source,
            AdapterOutcome.SUCCESS,
            jobs,
            diagnostics,
            page_count=page_count,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        _validate_source(source)
        _validate_job(source, job)
        detail = self._fetch_detail(job.canonical_url, include_description=True)
        if _normalize_text(detail.title) != job.title_normalized:
            raise ValueError("Aganitha detail title changed after listing discovery.")
        if _normalize_text(detail.location) != _normalize_text(job.location_original):
            raise ValueError("Aganitha detail location changed after listing discovery.")
        if detail.description is None:
            raise ValueError("Aganitha detail description was unavailable.")
        return replace(
            job,
            description=detail.description,
            description_hash=hashlib.sha256(detail.description.encode("utf-8")).hexdigest(),
            source_metadata={**job.source_metadata, "detail_retrieved": True},
        )

    def _fetch_detail(self, url: str, *, include_description: bool) -> _DetailData:
        try:
            response = self._client.get(
                url,
                accepted_content_types=("text/html",),
                referer=AGANITHA_CAREERS_URL,
            )
        except HttpRequestError as error:
            raise ValueError(f"Aganitha detail request failed: {error.category.value}") from error
        if response.final_url != url:
            raise ValueError("Aganitha detail redirected outside its canonical URL.")
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Aganitha detail was not valid UTF-8.") from error
        if is_access_block_html(document):
            raise ValueError("Aganitha detail returned an access-control page.")
        return _detail_data(document, include_description=include_description)


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != AGANITHA_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Aganitha adapter requires adapter_key={AGANITHA_ADAPTER_KEY}."
        )
    if source.careers_url != AGANITHA_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Aganitha adapter requires careers_url={AGANITHA_CAREERS_URL}."
        )


def _validate_job(source: CompanySource, job: NormalizedJob) -> None:
    if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
        raise AdapterConfigurationError("Aganitha detail job does not belong to the source.")
    canonical_url, external_id = _canonical_detail_url(job.canonical_url)
    if canonical_url != job.canonical_url or external_id != job.external_job_id:
        raise AdapterConfigurationError("Aganitha detail job identity is inconsistent.")


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ListingRow] = []
        self.item_depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.detail_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        tag = tag.casefold()
        if tag == "div" and "bdt-ep-accordion-item" in classes and self.item_depth == 0:
            self.item_depth = 1
            self.title_parts = []
            self.detail_href = None
            return
        if self.item_depth and tag == "div":
            self.item_depth += 1
        if not self.item_depth:
            return
        if tag == "span" and "bdt-ep-title-text" in classes and self.title_depth == 0:
            self.title_depth = 1
        elif self.title_depth and tag == "span":
            self.title_depth += 1
        if tag == "a":
            href = attributes.get("href")
            if isinstance(href, str) and _is_detail_url(href):
                self.detail_href = href

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self.title_depth and tag == "span":
            self.title_depth -= 1
        if not self.item_depth or tag != "div":
            return
        self.item_depth -= 1
        if self.item_depth != 0:
            return
        title = _normalize_whitespace(" ".join(self.title_parts))
        if not title or self.detail_href is None:
            self.rows.append(_ListingRow(title, "", ""))
            return
        canonical_url, external_id = _canonical_detail_url(self.detail_href)
        self.rows.append(_ListingRow(title, canonical_url, external_id))

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title_parts.append(data)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.main_depth = 0
        self.skip_depth = 0
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.location_parts: list[str] = []
        self.capture_title = False
        self.capture_location = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        tag = tag.casefold()
        if tag == "main" and "entry-content" in classes and not self.in_main:
            self.in_main = True
            self.main_depth = 1
            self.parts.append("\n")
            return
        if not self.in_main:
            return
        if tag == "main":
            self.main_depth += 1
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "h2" and not self.title_parts:
            self.capture_title = True
        if tag == "h3" and "bdt-ep-advanced-icon-box-title" in classes and not self.location_parts:
            self.capture_location = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if not self.in_main:
            return
        if tag in _SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "h2" and self.capture_title:
            self.capture_title = False
        if tag == "h3" and self.capture_location:
            self.capture_location = False
        if tag == "main":
            self.main_depth -= 1
            if self.main_depth == 0:
                self.in_main = False

    def handle_data(self, data: str) -> None:
        if not self.in_main or self.skip_depth:
            return
        self.parts.append(data)
        if self.capture_title:
            self.title_parts.append(data)
        if self.capture_location:
            self.location_parts.append(data)


def _listing_rows(document: str) -> list[_ListingRow]:
    parser = _ListingParser()
    parser.feed(document)
    parser.close()
    rows = parser.rows
    for row in rows:
        if not row.title or not row.canonical_url or not row.external_id:
            raise ValueError("Aganitha accordion contained an incomplete job row.")
    return rows


def _detail_data(document: str, *, include_description: bool) -> _DetailData:
    parser = _DetailParser()
    parser.feed(document)
    parser.close()
    title = _normalize_whitespace(" ".join(parser.title_parts))
    location = _normalize_whitespace(" ".join(parser.location_parts))
    if not title or not location:
        raise ValueError("Aganitha detail omitted its title or location.")
    description: str | None = None
    if include_description:
        lines = _normalized_lines(parser.parts)
        start = next(
            (
                index + 1
                for index, line in enumerate(lines)
                if line.casefold().startswith("apply here")
            ),
            None,
        )
        end = next(
            (
                index
                for index, line in enumerate(lines)
                if start is not None
                and index > start
                and line.casefold().startswith("other open positions")
            ),
            None,
        )
        if start is None or end is None or end <= start:
            raise ValueError("Aganitha detail description boundaries were unavailable.")
        description = "\n\n".join(lines[start:end]).strip()
        if len(description) < 80:
            raise ValueError("Aganitha detail description normalized to insufficient text.")
    return _DetailData(title, location, description)


def _normalized_job(
    source: CompanySource,
    row: _ListingRow,
    detail: _DetailData,
) -> NormalizedJob:
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=row.external_id,
        title_original=detail.title,
        title_normalized=_normalize_text(detail.title),
        location_original=detail.location,
        location_normalized=_normalized_locations(detail.location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=row.canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": AGANITHA_ADAPTER_KEY,
            "metadata_detail_retrieved": True,
        },
    )


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
        raise ValueError("Aganitha job URL must be a same-origin /careers/<slug>/ URL.")
    external_id = match.group(1)
    return f"https://{_HOST}/careers/{external_id}/", external_id


def _normalized_lines(parts: Iterable[str]) -> list[str]:
    text = "".join(parts).replace("\r", "")
    return [normalized for line in text.splitlines() if (normalized := _normalize_whitespace(line))]


def _normalized_locations(value: str) -> tuple[str, ...]:
    result = tuple(
        dict.fromkeys(
            _normalize_text(piece) for piece in re.split(r"[,|;/]", value) if piece.strip()
        )
    )
    return result or ("location unavailable",)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text(value: str) -> str:
    return _normalize_whitespace(value).casefold()


def _titles_compatible(left: str, right: str) -> bool:
    if _normalize_text(left) == _normalize_text(right):
        return True
    left_tokens = {token for token in re.findall(r"[a-z0-9]+", left.casefold()) if len(token) >= 3}
    right_tokens = {
        token for token in re.findall(r"[a-z0-9]+", right.casefold()) if len(token) >= 3
    }
    shared = left_tokens & right_tokens
    return len(shared) >= 2 and (left_tokens <= right_tokens or right_tokens <= left_tokens)


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


def _failed(
    source: CompanySource,
    category: str,
    message: str,
    *,
    page_count: int,
) -> AdapterResult:
    return _result(
        source,
        AdapterOutcome.FAILED,
        [],
        [_diagnostic(category, DiagnosticSeverity.ERROR, message)],
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
