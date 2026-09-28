"""Deterministic adapter for GalaxEye's officially linked Zoho Recruit RSS feed."""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlsplit

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

GALAXEYE_ADAPTER_KEY = "galaxeye_zoho_rss"
GALAXEYE_CAREERS_URL = "https://careers.galaxeye.space/jobs/Careers"
GALAXEYE_RSS_URL = "https://galaxeye-pranitgalaxeyespace.zohorecruit.in/jobs/Careers/rss"

_HOST = "careers.galaxeye.space"
_DETAIL_PATH_PATTERN = re.compile(r"/jobs/Careers/([0-9]+)/([A-Za-z0-9%._~!$&'()*+,;=:@-]+)")
_DESCRIPTION_MARKER = re.compile(r"<span\b[^>]*\bid=[\"']spandesc[\"']", re.IGNORECASE)
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


class GalaxEyeZohoAdapter:
    """Read GalaxEye's complete public Zoho RSS inventory and deferred detail pages."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = GALAXEYE_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                GALAXEYE_RSS_URL,
                accepted_content_types=("application/rss+xml", "application/xml", "text/xml"),
                referer=GALAXEYE_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url.rstrip("/") != GALAXEYE_RSS_URL.rstrip("/"):
            return _failed(source, "unexpected_redirect", "GalaxEye RSS feed redirected.")

        try:
            document = response.body.decode("utf-8")
            channel = _rss_channel(document)
            channel_title = _child_text(channel, "title")
            channel_link = _child_text(channel, "link")
            if "GALAXEYE SPACE SOLUTIONS PRIVATE LIMITED" not in channel_title:
                raise ValueError("GalaxEye RSS publisher title was unexpected.")
            if channel_link.rstrip("/") != f"{GALAXEYE_CAREERS_URL}/rss":
                raise ValueError("GalaxEye RSS channel link was unexpected.")
            items = [child for child in channel if _local_name(child.tag) == "item"]
        except (ElementTree.ParseError, UnicodeDecodeError, ValueError) as error:
            return _failed(source, "unsupported_schema", str(error))

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(items):
            try:
                job = _normalize_item(source, item)
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "malformed_job",
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
                    page_count=1,
                )
            external_id = job.external_job_id
            if external_id is None:
                raise AssertionError("GalaxEye jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "GalaxEye RSS returned a duplicate job GUID.",
                        job_index=index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    diagnostics,
                    page_count=1,
                )
            seen_ids.add(external_id)
            jobs.append(job)

        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            diagnostics,
            page_count=1,
            complete=True,
        )

def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != GALAXEYE_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"GalaxEye adapter requires adapter_key={GALAXEYE_ADAPTER_KEY}."
        )
    if source.careers_url != GALAXEYE_CAREERS_URL:
        raise AdapterConfigurationError(
            f"GalaxEye adapter requires careers_url={GALAXEYE_CAREERS_URL}."
        )


def _rss_channel(document: str) -> ElementTree.Element:
    if "<!DOCTYPE" in document.upper():
        raise ValueError("GalaxEye RSS must not contain a document type declaration.")
    root = ElementTree.fromstring(document)
    if _local_name(root.tag) != "rss":
        raise ValueError("GalaxEye feed root must be rss.")
    channels = [child for child in root if _local_name(child.tag) == "channel"]
    if len(channels) != 1:
        raise ValueError("GalaxEye RSS must contain exactly one channel.")
    return channels[0]


def _normalize_item(source: CompanySource, item: ElementTree.Element) -> NormalizedJob:
    title = html.unescape(_child_text(item, "title"))
    guid = _child_text(item, "guid")
    if not guid.isdigit():
        raise ValueError("GalaxEye RSS guid must be numeric.")
    canonical_url, external_id = _canonical_detail_url(_child_text(item, "link"))
    if external_id != guid:
        raise ValueError("GalaxEye RSS guid does not match its detail URL.")
    raw_description = _child_text(item, "description")
    location, category = _listing_metadata(raw_description)
    description = _detail_description(raw_description)
    published_raw = _child_text(item, "pubDate")
    try:
        published_at = datetime.strptime(
            published_raw,
            "%a, %d %b %Y %H:%M:%S IST",
        ).date()
    except ValueError as error:
        raise ValueError("GalaxEye RSS pubDate is invalid.") from error
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=guid,
        title_original=_normalize_whitespace(title),
        title_normalized=_normalize_text(title),
        location_original=location,
        location_normalized=_normalized_locations(location),
        published_at=published_at,
        published_at_raw=published_raw,
        date_basis=DateBasis.PUBLISHED,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": GALAXEYE_ADAPTER_KEY,
            "category": category,
            "rss_description_in_listing_payload": True,
        },
    )


def _listing_metadata(raw_description: str) -> tuple[str, str | None]:
    marker = _DESCRIPTION_MARKER.search(raw_description)
    prefix = raw_description[: marker.start()] if marker is not None else raw_description
    lines = _html_lines(prefix)
    location = next(
        (
            line.split(":", 1)[1].strip()
            for line in lines
            if line.casefold().startswith("location:")
        ),
        None,
    )
    if not location:
        raise ValueError("GalaxEye RSS description has no listing location.")
    category = next(
        (
            line.split(":", 1)[1].strip()
            for line in lines
            if line.casefold().startswith("category:")
        ),
        None,
    )
    return _normalize_whitespace(location), _normalize_whitespace(category) if category else None


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "svg", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif self.skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def _detail_description(document: str) -> str:
    marker = _DESCRIPTION_MARKER.search(document)
    if marker is None:
        raise ValueError("GalaxEye RSS description has no spandesc marker.")
    description = "\n\n".join(_html_lines(document[marker.end() :])).strip()
    if len(description) < 80:
        raise ValueError("GalaxEye detail description normalized to insufficient text.")
    return description


def _html_lines(value: str) -> list[str]:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    return _normalized_lines(parser.parts)


def _canonical_detail_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    match = _DETAIL_PATH_PATTERN.fullmatch(parsed.path.rstrip("/"))
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or query != [("source", "RSS")]
        or match is None
    ):
        raise ValueError("GalaxEye job URL must be a canonical same-origin RSS detail URL.")
    external_id = match.group(1)
    slug = match.group(2)
    return f"https://{_HOST}/jobs/Careers/{external_id}/{slug}?source=RSS", external_id


def _child_text(element: ElementTree.Element, name: str) -> str:
    matches = [child for child in element if _local_name(child.tag) == name]
    if len(matches) != 1 or matches[0].text is None or not matches[0].text.strip():
        raise ValueError(f"GalaxEye RSS item field {name} must occur exactly once.")
    return matches[0].text.strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalized_lines(parts: Iterable[str]) -> list[str]:
    text = "".join(parts).replace("\r", "")
    return [
        normalized
        for line in text.splitlines()
        if (normalized := _normalize_whitespace(line))
    ]


def _normalized_locations(value: str) -> tuple[str, ...]:
    normalized = _normalize_text(value)
    return (normalized,)


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
