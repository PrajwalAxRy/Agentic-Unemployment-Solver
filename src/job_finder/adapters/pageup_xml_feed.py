"""Deterministic parser for PageUp/Happydance public XML job exports."""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpFailureCategory, HttpRequestError
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

PAGEUP_XML_ADAPTER_KEY = "pageup_xml_feed"

_JOB_PATH_PATTERN = re.compile(r"/(?:[a-z]{2}/)?jobs/([0-9]+)/([^/]+)/?")
_ENCODED_SLUG_PATTERN = re.compile(r"(?:[A-Za-z0-9_-]|%[0-9A-Fa-f]{2})+")
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
    "ul",
}


class PageUpXmlFeedAdapter:
    """Retrieve a complete public PageUp XML export in one bounded request."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = PAGEUP_XML_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        feed_url, expected_publisher = _validate_source(source)
        try:
            response = self._client.get(
                feed_url,
                accepted_content_types=("text/xml", "application/xml"),
                referer=source.careers_url,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                0,
                [request_failure_diagnostic(error)],
            )

        if _canonical_url(response.final_url) != feed_url:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "PageUp XML feed redirected outside the configured export URL.",
                    )
                ],
            )
        try:
            document = response.body.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "invalid_encoding",
                        DiagnosticSeverity.ERROR,
                        "PageUp XML feed was not valid UTF-8.",
                    )
                ],
            )
        if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "unsafe_xml",
                        DiagnosticSeverity.ERROR,
                        "PageUp XML feed contained a document type or entity declaration.",
                    )
                ],
            )
        try:
            root = ElementTree.fromstring(document)
        except ElementTree.ParseError:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "invalid_xml",
                        DiagnosticSeverity.ERROR,
                        "PageUp XML feed was malformed.",
                    )
                ],
            )
        if root.tag != "source":
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "unsupported_schema",
                        DiagnosticSeverity.ERROR,
                        "PageUp XML feed root must be source.",
                    )
                ],
            )
        try:
            publisher = _required_child_text(root, "publisher", "PageUp source")
            publisher_url = _required_child_text(root, "publisherUrl", "PageUp source")
            last_build_raw = _required_child_text(root, "lastBuildDate", "PageUp source")
            last_build_at = _rfc2822_datetime(last_build_raw, "PageUp lastBuildDate")
        except ValueError as error:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [_diagnostic("unsupported_schema", DiagnosticSeverity.ERROR, str(error))],
            )
        if publisher != expected_publisher:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "publisher_mismatch",
                        DiagnosticSeverity.ERROR,
                        "PageUp XML publisher did not match the configured company.",
                    )
                ],
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        jobs_by_id: dict[str, NormalizedJob] = {}
        for job_index, element in enumerate(root.findall("job")):
            try:
                job = _normalize_job(
                    source,
                    element,
                    feed_url=feed_url,
                    publisher=publisher,
                    publisher_url=publisher_url,
                    last_build_raw=last_build_raw,
                    last_build_at=last_build_at,
                )
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=job_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    1,
                    diagnostics,
                )
            external_id = job.external_job_id
            if external_id is None:
                raise AssertionError("PageUp normalized jobs require an external ID")
            existing = jobs_by_id.get(external_id)
            if existing == job:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id_collapsed",
                        DiagnosticSeverity.WARNING,
                        "PageUp XML feed repeated an identical job row; duplicate collapsed.",
                        job_index=job_index,
                    )
                )
                continue
            if existing is not None:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "PageUp XML feed reused an API job ID for conflicting job data.",
                        job_index=job_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, 1, diagnostics)
            jobs_by_id[external_id] = job
            jobs.append(job)

        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            1,
            diagnostics,
            complete=True,
        )


def _validate_source(source: CompanySource) -> tuple[str, str]:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key", "feed_url", "publisher"),
    )
    if parameters["adapter_key"] != PAGEUP_XML_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"PageUp XML adapter requires adapter_key={PAGEUP_XML_ADAPTER_KEY}"
        )
    if source.careers_url is None:
        raise AdapterConfigurationError("PageUp XML adapter requires careers_url")
    careers = urlsplit(source.careers_url)
    feed_url = _canonical_url(parameters["feed_url"])
    feed = urlsplit(feed_url)
    if (
        careers.scheme != "https"
        or feed.scheme != "https"
        or not careers.hostname
        or careers.hostname != feed.hostname
        or careers.port is not None
        or feed.port is not None
        or feed.fragment
        or not feed.path.endswith("/jobs/xml/")
        or parse_qs(feed.query) != {"rss": ["true"]}
    ):
        raise AdapterConfigurationError(
            "PageUp XML adapter requires an HTTPS same-host /jobs/xml/?rss=true feed_url"
        )
    return feed_url, parameters["publisher"]


def _normalize_job(
    source: CompanySource,
    element: ElementTree.Element,
    *,
    feed_url: str,
    publisher: str,
    publisher_url: str,
    last_build_raw: str,
    last_build_at: datetime,
) -> NormalizedJob:
    title = _required_child_text(element, "title", "PageUp job")
    external_id = _required_child_text(element, "apijobid", "PageUp job")
    if not external_id.isdigit():
        raise ValueError("PageUp apijobid must be numeric.")
    requisition_id = _required_child_text(element, "requisitionid", "PageUp job")
    reference_number = _required_child_text(element, "referencenumber", "PageUp job")
    canonical_url = _job_url(
        _required_child_text(element, "url", "PageUp job"),
        feed_url=feed_url,
        external_id=external_id,
    )
    date_raw = _required_child_text(element, "date", "PageUp job")
    published_at = _rfc2822_datetime(date_raw, "PageUp job date")
    location_parts = _unique_strings(
        _optional_child_text(element, field) for field in ("city", "state", "country")
    )
    if not location_parts:
        raise ValueError("PageUp job must contain a city, state, or country.")
    location = ", ".join(location_parts)
    raw_description = _required_child_text(element, "description", "PageUp job")
    description = _plain_text(html.unescape(raw_description))
    if not description:
        raise ValueError("PageUp job description normalized to empty text.")
    company = _optional_child_text(element, "company")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location),
        published_at=published_at,
        published_at_raw=date_raw,
        date_basis=DateBasis.PUBLISHED,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": PAGEUP_XML_ADAPTER_KEY,
            "publisher": publisher,
            "publisher_url": publisher_url,
            "last_build_date": last_build_raw,
            "last_build_at": last_build_at.isoformat(),
            "requisition_id": requisition_id,
            "reference_number": reference_number,
            "company": company,
        },
    )


def _job_url(value: str, *, feed_url: str, external_id: str) -> str:
    parsed = urlsplit(value)
    feed = urlsplit(feed_url)
    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    valid_slug = match is not None and _valid_slug(match.group(2))
    if (
        parsed.scheme != "https"
        or parsed.hostname != feed.hostname
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or match is None
        or match.group(1) != external_id
        or not valid_slug
    ):
        raise ValueError("PageUp job URL must be an official path matching apijobid.")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _valid_slug(value: str) -> bool:
    if not _ENCODED_SLUG_PATTERN.fullmatch(value):
        return False
    decoded = unquote(value)
    return bool(decoded) and all(character.isalnum() or character in "-_" for character in decoded)


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _required_child_text(element: ElementTree.Element, tag: str, context: str) -> str:
    value = _optional_child_text(element, tag)
    if value is None:
        raise ValueError(f"{context} field {tag} must be non-empty.")
    return value


def _optional_child_text(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None or not child.text.strip():
        return None
    return child.text.strip()


def _rfc2822_datetime(value: str, field: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an RFC 2822 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _unique_strings(values: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
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
    **context: int | str,
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
