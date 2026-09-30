"""Deterministic adapter for Qure.ai's officially linked Zoho careers board."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from job_finder.adapters._support import diagnostic, request_outcome
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
from job_finder.core.validation import clean_optional, required_string
from job_finder.normalization.jobs import normalize_source_locations as _shared_locations
from job_finder.normalization.jobs import normalize_text, normalize_title

_WHITESPACE_RUN = re.compile(r"\s+")

QURE_ADAPTER_KEY = "qure_zoho_embedded"
QURE_CAREERS_URL = "https://career.qure.ai/jobs/Careers"

_HOST = "career.qure.ai"
_DETAIL_PATH_PATTERN = re.compile(r"/jobs/Careers/([0-9]+)/([A-Za-z0-9%._~!$&'()*+,;=:@-]+)")
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


class QureCareersAdapter:
    """Read Qure.ai's complete embedded collection with bundled descriptions."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = QURE_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                QURE_CAREERS_URL,
                accepted_content_types=("text/html",),
                referer=QURE_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url.rstrip("/") != QURE_CAREERS_URL.rstrip("/"):
            return _failed(source, "unexpected_redirect", "Qure.ai careers board redirected.")
        try:
            document = response.body.decode("utf-8")
        except UnicodeDecodeError:
            return _failed(source, "invalid_encoding", "Qure.ai careers HTML was not valid UTF-8.")
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
            parser = _QurePageParser()
            parser.feed(document)
            parser.close()
            rows = parser.rows()
            detail_urls = parser.detail_urls
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            return _failed(source, "unsupported_schema", str(error))
        if not rows:
            return _failed(
                source,
                "unproved_empty_inventory",
                "Qure.ai exposed no independently proved empty-state contract.",
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(rows):
            try:
                job = _normalize_job(source, raw, detail_urls)
            except ValueError as error:
                diagnostics.append(
                    diagnostic(
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
                raise AssertionError("Qure.ai jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Qure.ai returned a duplicate job ID.",
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
        if not set(detail_urls).issubset(seen_ids):
            return _result(
                source,
                AdapterOutcome.SUSPICIOUS,
                jobs,
                [
                    *diagnostics,
                    diagnostic(
                        "identity_collection_mismatch",
                        DiagnosticSeverity.ERROR,
                        "Qure.ai embedded rows and visible detail links did not match.",
                    ),
                ],
                page_count=1,
            )
        if len(detail_urls) < len(jobs):
            diagnostics.append(
                diagnostic(
                    "canonical_detail_urls_derived",
                    DiagnosticSeverity.INFO,
                    "Qure.ai detail URLs were derived with the rendered Zoho title-slug rule.",
                    count=len(jobs) - len(detail_urls),
                )
            )
        nonstandard_state_count = sum(
            job.source_metadata.get("publish_flag") is not True
            or job.source_metadata.get("keep_on_career_site") is not False
            for job in jobs
        )
        if nonstandard_state_count:
            diagnostics.append(
                diagnostic(
                    "visible_rows_with_workflow_flags",
                    DiagnosticSeverity.INFO,
                    "Qure.ai visibly rendered rows with nonstandard Zoho workflow flags.",
                    count=nonstandard_state_count,
                )
            )
        diagnostics.append(
            diagnostic(
                "unverified_date_opened",
                DiagnosticSeverity.WARNING,
                "Qure.ai exposes Date_Opened, not a verified publication timestamp.",
                count=len(jobs),
            )
        )
        return _result(
            source,
            AdapterOutcome.SUCCESS,
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
    if parameters["adapter_key"] != QURE_ADAPTER_KEY:
        raise AdapterConfigurationError(f"Qure.ai adapter requires adapter_key={QURE_ADAPTER_KEY}.")
    if source.careers_url != QURE_CAREERS_URL:
        raise AdapterConfigurationError(f"Qure.ai adapter requires careers_url={QURE_CAREERS_URL}.")


class _QurePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inventory_values: list[str] = []
        self.detail_urls: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        tag = tag.casefold()
        if tag == "input":
            value = attributes.get("value")
            if isinstance(value, str) and '"Posting_Title"' in value and '"Date_Opened"' in value:
                self.inventory_values.append(value)
        elif tag == "a":
            href = attributes.get("href")
            if isinstance(href, str) and "/jobs/Careers/" in href:
                canonical_url, external_id = _canonical_detail_url(href)
                current = self.detail_urls.setdefault(external_id, canonical_url)
                if current != canonical_url:
                    raise ValueError("Qure.ai returned conflicting detail URLs for one job ID.")

    def rows(self) -> list[Mapping[str, object]]:
        if len(self.inventory_values) != 1:
            raise ValueError("Qure.ai must expose exactly one embedded jobs collection.")
        payload: Any = json.loads(self.inventory_values[0])
        if not isinstance(payload, list):
            raise ValueError("Qure.ai embedded jobs collection must be an array.")
        rows: list[Mapping[str, object]] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise ValueError("Qure.ai embedded job rows must be objects.")
            rows.append(item)
        return rows


def _normalize_job(
    source: CompanySource,
    raw: Mapping[str, object],
    detail_urls: Mapping[str, str],
) -> NormalizedJob:
    external_id = _numeric_string(raw.get("id"), "Qure.ai job id")
    title = required_string(raw, "Posting_Title")
    opening_name = required_string(raw, "Job_Opening_Name")
    if normalize_text(title) != normalize_text(opening_name):
        raise ValueError("Qure.ai Posting_Title and Job_Opening_Name disagree.")
    publish_flag = raw.get("Publish")
    if not isinstance(publish_flag, bool):
        raise ValueError("Qure.ai Publish must be boolean.")
    is_locked = raw.get("Is_Locked")
    if not isinstance(is_locked, bool):
        raise ValueError("Qure.ai Is_Locked must be boolean.")
    keep_on_career_site = raw.get("Keep_on_Career_Site")
    if not isinstance(keep_on_career_site, bool):
        raise ValueError("Qure.ai Keep_on_Career_Site must be boolean.")
    canonical_url = _derived_detail_url(external_id, title)
    visible_url = detail_urls.get(external_id)
    if visible_url is not None and visible_url != canonical_url:
        raise ValueError("Qure.ai visible detail URL does not match its deterministic title slug.")

    location_parts: list[str] = []
    if raw.get("Remote_Job") is True:
        location_parts.append("Remote")
    elif not isinstance(raw.get("Remote_Job"), bool):
        raise ValueError("Qure.ai Remote_Job must be boolean.")
    for field in ("City", "State", "Country"):
        value = raw.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Qure.ai {field} must be text or null.")
        normalized = _normalize_whitespace(value)
        if normalized and normalized.casefold() not in {item.casefold() for item in location_parts}:
            location_parts.append(normalized)
    if not location_parts:
        raise ValueError("Qure.ai job has no location evidence.")
    location = ", ".join(location_parts)

    date_raw = required_string(raw, "Date_Opened")
    try:
        opened_at = date.fromisoformat(date_raw)
    except ValueError as error:
        raise ValueError("Qure.ai Date_Opened must be an ISO date.") from error
    description = _html_text(required_string(raw, "Job_Description"))
    if len(description) < 80:
        raise ValueError("Qure.ai job description normalized to insufficient text.")
    experience = raw.get("Work_Experience")
    if experience is not None and not isinstance(experience, str):
        raise ValueError("Qure.ai Work_Experience must be text or null.")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=_normalize_whitespace(title),
        title_normalized=normalize_title(title),
        location_original=location,
        location_normalized=_shared_locations(location_parts),
        published_at=opened_at,
        published_at_raw=date_raw,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": QURE_ADAPTER_KEY,
            "date_opened_unverified": True,
            "industry": clean_optional(raw.get("Industry")),
            "is_locked": is_locked,
            "job_type": clean_optional(raw.get("Job_Type")),
            "keep_on_career_site": keep_on_career_site,
            "publish_flag": publish_flag,
            "work_experience": clean_optional(experience),
        },
    )


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
        or query != [("source", "CareerSite")]
        or match is None
    ):
        raise ValueError("Qure.ai job URL must be a canonical same-origin detail URL.")
    external_id = match.group(1)
    slug = match.group(2)
    return f"https://{_HOST}/jobs/Careers/{external_id}/{slug}?source=CareerSite", external_id


def _derived_detail_url(external_id: str, title: str) -> str:
    try:
        title.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("Qure.ai title slug derivation currently requires ASCII text.") from error
    slug = re.sub(r"[^A-Za-z0-9-]", "-", _normalize_whitespace(title))
    if not slug.strip("-"):
        raise ValueError("Qure.ai title did not produce a usable detail slug.")
    return f"https://{_HOST}/jobs/Careers/{external_id}/{slug}?source=CareerSite"


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
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


def _html_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    return "\n".join(
        line
        for line in (_normalize_whitespace(part) for part in "".join(parser.parts).splitlines())
        if line
    )


def _numeric_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError(f"{context} must be numeric text.")
    return value


def _failed(source: CompanySource, category: str, message: str) -> AdapterResult:
    return _result(
        source,
        AdapterOutcome.FAILED,
        [],
        [diagnostic(category, DiagnosticSeverity.ERROR, message)],
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
