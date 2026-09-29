"""Deterministic adapter for Swiggy's public MyNextHire careers inventory."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

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
from job_finder.normalization.jobs import normalize_source_locations as _shared_locations
from job_finder.normalization.jobs import normalize_text, normalize_title

_WHITESPACE_RUN = re.compile(r"\s+")

SWIGGY_ADAPTER_KEY = "swiggy_mynexthire_inventory"
SWIGGY_CAREERS_URL = "https://careers.swiggy.com/"
SWIGGY_JOBS_API = "https://swiggy.mynexthire.com/employer/careers/reqlist/get"

_REQUEST_PAYLOAD: Mapping[str, object] = {
    "source": "careers",
    "code": "",
    "filterByBuId": -1,
}
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


class SwiggyCareersAdapter:
    """Read Swiggy's complete public requisition collection with inline descriptions."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = SWIGGY_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.post_json(
                SWIGGY_JOBS_API,
                _REQUEST_PAYLOAD,
                accepted_content_types=("application/json",),
                referer=SWIGGY_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url != SWIGGY_JOBS_API:
            return _failed(source, "unexpected_redirect", "Swiggy jobs API redirected.")
        try:
            payload: Any = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _failed(source, "invalid_json", "Swiggy jobs API was not valid JSON.")
        if not isinstance(payload, Mapping):
            return _failed(source, "unsupported_schema", "Swiggy response root must be an object.")
        raw_jobs = payload.get("reqDetailsBOList")
        if not isinstance(raw_jobs, list):
            return _failed(
                source,
                "unsupported_schema",
                "Swiggy response omitted its requisition collection.",
            )
        if not raw_jobs:
            return _failed(
                source,
                "unproved_empty_inventory",
                "Swiggy exposed no independently proved empty-state contract.",
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        short_description_count = 0
        for index, raw in enumerate(raw_jobs):
            try:
                job = _normalize_job(source, raw)
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
                raise AssertionError("Swiggy jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Swiggy returned a duplicate requisition ID.",
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
            short_description_count += int(bool(job.source_metadata["short_description"]))

        if short_description_count:
            diagnostics.append(
                _diagnostic(
                    "short_source_description",
                    DiagnosticSeverity.WARNING,
                    "Swiggy supplied unusually short but non-empty job descriptions.",
                    count=short_description_count,
                )
            )
        diagnostics.append(
            _diagnostic(
                "unverified_approved_on",
                DiagnosticSeverity.WARNING,
                "Swiggy exposes requisition approval timestamps, not verified publication dates.",
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
    if parameters["adapter_key"] != SWIGGY_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Swiggy adapter requires adapter_key={SWIGGY_ADAPTER_KEY}."
        )
    if source.careers_url != SWIGGY_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Swiggy adapter requires careers_url={SWIGGY_CAREERS_URL}."
        )


def _normalize_job(source: CompanySource, value: object) -> NormalizedJob:
    if not isinstance(value, Mapping):
        raise ValueError("Swiggy requisition must be an object.")
    external_id = str(_positive_int(value.get("reqId"), "Swiggy reqId"))
    if value.get("statusId") != 3:
        raise ValueError("Swiggy requisition did not have the verified open statusId=3.")
    title = _required_string(value, "reqTitle", "Swiggy requisition")
    location = _required_string(value, "location", "Swiggy requisition")
    _validate_location_list(value.get("locationList"), location)
    description = _html_text(_required_string(value, "jdDisplay", "Swiggy requisition"))
    if not description:
        raise ValueError("Swiggy job description normalized to empty text.")
    approved_raw = _required_string(value, "approvedOn", "Swiggy requisition")
    try:
        approved_at = datetime.strptime(approved_raw, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError as error:
        raise ValueError(
            "Swiggy approvedOn did not match the verified timestamp format."
        ) from error

    minimum_experience = _non_negative_number(value.get("expMin"), "Swiggy expMin")
    maximum_experience = _non_negative_number(value.get("expMax"), "Swiggy expMax")
    if minimum_experience > maximum_experience:
        raise ValueError("Swiggy minimum experience exceeds maximum experience.")
    employment_type = _required_string(value, "employmentType", "Swiggy requisition")
    total_positions = _positive_int(value.get("totalPositions"), "Swiggy totalPositions")

    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=_normalize_whitespace(title),
        title_normalized=normalize_title(title),
        location_original=_normalize_whitespace(location),
        location_normalized=_shared_locations(location),
        published_at=approved_at,
        published_at_raw=approved_raw,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=_canonical_job_url(int(external_id)),
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": SWIGGY_ADAPTER_KEY,
            "approval_date_unverified": True,
            "business_unit": _optional_string(value.get("buName")),
            "career_stream": _optional_string(value.get("careerStream")),
            "employment_type": employment_type,
            "minimum_experience_years": minimum_experience,
            "maximum_experience_years": maximum_experience,
            "total_positions": total_positions,
            "short_description": len(description) < 80,
        },
    )


def _canonical_job_url(req_id: int) -> str:
    route_state = {
        "pageType": "jd",
        "cvSource": "careers",
        "reqId": req_id,
        "requester": {"id": "", "code": "", "name": ""},
        "page": "careers",
        "bufilter": -1,
        "customFields": {},
    }
    encoded_state = base64.b64encode(
        json.dumps(route_state, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    encoded_query = quote(f"src=careers&p={encoded_state}", safe="")
    return f"{SWIGGY_CAREERS_URL}#/careers?{encoded_query}"


def _validate_location_list(value: object, location: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("Swiggy locationList must be a non-empty array.")
    candidates: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("Swiggy locationList entries must be objects.")
        for field in ("address", "office"):
            text = item.get(field)
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Swiggy locationList {field} must be non-empty text.")
            candidates.add(normalize_text(text))
    if normalize_text(location) not in candidates:
        raise ValueError("Swiggy location did not match its locationList.")


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


def _required_string(raw: Mapping[str, object], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} {field} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Swiggy optional metadata must be text or null.")
    return _normalize_whitespace(value) or None


def _positive_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{context} must be a positive integer.")
    return value


def _non_negative_number(value: object, context: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} must be a non-negative number.")
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


def _normalize_whitespace(value: str) -> str:
    """Collapse runs of whitespace, preserving case.

    Distinct from the shared ``normalize_text``: several adapters need the original
    casing for display fields such as titles and locations.
    """
    return _WHITESPACE_RUN.sub(" ", value).strip()
