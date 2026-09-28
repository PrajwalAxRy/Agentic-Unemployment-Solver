"""Deterministic adapter for Navi's complete public careers API."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit, urlunsplit

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

NAVI_ADAPTER_KEY = "navi_public_careers_api"
NAVI_CAREERS_URL = "https://navi.com/careers/jobs"
NAVI_JOBS_API = "https://navi.com/api/careers/jobs"
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
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


class NaviCareersAdapter:
    """Retrieve and reconcile Navi's one-response public job collection."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = NAVI_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                NAVI_JOBS_API,
                accepted_content_types=("application/json",),
                referer=NAVI_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url != NAVI_JOBS_API:
            return _failed(source, "unexpected_redirect", "Navi jobs API redirected.")
        try:
            root = _required_mapping(json.loads(response.body), "Navi response")
            total = _non_negative_int(root.get("Total"), "Navi Total")
            filtered = _non_negative_int(root.get("FilteredCount"), "Navi FilteredCount")
            raw_jobs = _required_list(root.get("Jobs"), "Navi Jobs")
            if total != filtered or total != len(raw_jobs):
                raise ValueError("Navi totals do not match the returned Jobs collection.")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            return _failed(source, "unsupported_schema", str(error))

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        for index, raw_job in enumerate(raw_jobs):
            try:
                job = _normalize_job(source, raw_job)
            except (json.JSONDecodeError, ValueError) as error:
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
                raise AssertionError("Navi jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Navi returned a duplicate JobId.",
                        job_index=index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, diagnostics, page_count=1)
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
    if parameters["adapter_key"] != NAVI_ADAPTER_KEY:
        raise AdapterConfigurationError(f"Navi adapter requires adapter_key={NAVI_ADAPTER_KEY}.")
    if source.careers_url != NAVI_CAREERS_URL:
        raise AdapterConfigurationError(f"Navi adapter requires careers_url={NAVI_CAREERS_URL}.")


def _normalize_job(source: CompanySource, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "Navi job")
    external_id = _required_string(raw, "JobId", "Navi job")
    if _UUID_PATTERN.fullmatch(external_id) is None:
        raise ValueError("Navi JobId must be a UUID.")
    company_name = _required_string(raw, "CompanyName", "Navi job")
    if company_name not in {"Navi", "Navi Limited"}:
        raise ValueError("Navi job CompanyName did not identify Navi.")
    title = _required_string(raw, "JobTitle", "Navi job")
    canonical_url = _job_url(_required_string(raw, "ApplyUrl", "Navi job"), external_id)
    location_raw = _required_string(raw, "Location", "Navi job")
    locations = _location_values(location_raw)
    description_html = _required_string(raw, "JobDescriptionV2", "Navi job")
    description = _plain_text(description_html)
    if not description:
        raise ValueError("Navi JobDescriptionV2 normalized to empty text.")
    published_raw = _required_string(raw, "PublishedDate", "Navi job")
    published_at = _timestamp(published_raw, "Navi PublishedDate")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id.casefold(),
        title_original=title,
        title_normalized=_normalize_text(title),
        location_original=" | ".join(locations),
        location_normalized=_normalized_locations(locations),
        published_at=published_at,
        published_at_raw=published_raw,
        date_basis=DateBasis.PUBLISHED,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": NAVI_ADAPTER_KEY,
            "company_name": company_name,
            "job_code": _required_string(raw, "JobCode", "Navi job"),
            "department": _required_string(raw, "Department", "Navi job"),
            "job_type": _required_string(raw, "JobType", "Navi job"),
        },
    )


def _location_values(value: str) -> list[str]:
    payload = json.loads(value)
    items = _required_list(payload, "Navi Location JSON")
    locations: list[str] = []
    for item in items:
        raw = _required_mapping(item, "Navi Location item")
        address = _required_string(raw, "Address", "Navi Location item")
        if address not in locations:
            locations.append(address)
    if not locations:
        raise ValueError("Navi Location JSON must contain at least one address.")
    return locations


def _job_url(value: str, external_id: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "navi.turbohire.co"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != f"/job/publicjobs/{external_id}"
        or parse_qs(parsed.query) != {"utm_source": ["CareerPage"]}
        or parsed.fragment
    ):
        raise ValueError("Navi ApplyUrl did not match its JobId.")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""))


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
    parser.feed(html.unescape(value))
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed


def _normalized_locations(values: list[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _normalize_text(piece)
            for value in values
            for piece in re.split(r"[,|;/]", value)
            if piece.strip()
        )
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _required_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    return value


def _required_string(raw: Mapping[object, object], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} field {key} must be a non-empty string.")
    return re.sub(r"\s+", " ", value).strip()


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer.")
    return value


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
