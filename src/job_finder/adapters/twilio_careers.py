"""Deterministic adapter for Twilio's branded public Eightfold careers APIs."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any

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

TWILIO_ADAPTER_KEY = "twilio_public_careers_api"
TWILIO_CAREERS_URL = "https://jobs.twilio.com/careers?domain=twilio.com&hl=en"
TWILIO_API_ROOT = "https://jobs.twilio.com/api/pcsx"

_PAGE_SIZE = 10
_MAX_PAGES = 100


class TwilioCareersAdapter:
    """Read Twilio's complete branded search API and deferred public job details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = TWILIO_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None
        page_count = 0

        for page_index in range(_MAX_PAGES):
            start = page_index * _PAGE_SIZE
            endpoint = _search_url(start)
            try:
                response = self._client.get(
                    endpoint,
                    accepted_content_types=("application/json",),
                    referer=TWILIO_CAREERS_URL,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    diagnostics,
                    page_count=page_count,
                )
            page_count += 1
            if response.final_url != endpoint:
                diagnostics.append(
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "Twilio search API redirected.",
                        page_index=page_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_count=page_count,
                )
            try:
                payload: Any = json.loads(response.body)
                data = _response_data(payload, "Twilio search response")
                positions = data.get("positions")
                total = data.get("count")
                if not isinstance(positions, list):
                    raise ValueError("Twilio search response positions must be an array.")
                if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                    raise ValueError("Twilio search response count must be non-negative.")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                diagnostics.append(
                    _diagnostic(
                        "unsupported_schema",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        page_index=page_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_count=page_count,
                )

            if len(positions) > _PAGE_SIZE:
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    page_count,
                    "page_size_exceeded",
                    "Twilio returned more jobs than the verified page size.",
                )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    page_count,
                    "inconsistent_total",
                    "Twilio's job count changed during pagination.",
                )
            if not positions and len(jobs) < total:
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    page_count,
                    "premature_empty_page",
                    "Twilio returned an empty page before its reported count.",
                )

            for job_index, raw_job in enumerate(positions):
                try:
                    job = _normalize_listing(source, raw_job)
                except ValueError as error:
                    diagnostics.append(
                        _diagnostic(
                            "malformed_job",
                            DiagnosticSeverity.ERROR,
                            str(error),
                            page_index=page_index,
                            job_index=job_index,
                        )
                    )
                    return _result(
                        source,
                        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                        jobs,
                        diagnostics,
                        page_count=page_count,
                    )
                external_id = job.external_job_id
                if external_id is None:
                    raise AssertionError("Twilio jobs require an external ID")
                if external_id in seen_ids:
                    return _suspicious(
                        source,
                        jobs,
                        diagnostics,
                        page_count,
                        "duplicate_job_id",
                        "Twilio pagination returned a duplicate job ID.",
                    )
                seen_ids.add(external_id)
                jobs.append(job)

            if len(jobs) > total:
                return _suspicious(
                    source,
                    jobs,
                    diagnostics,
                    page_count,
                    "collection_exceeds_total",
                    "Twilio returned more jobs than its reported count.",
                )
            if len(jobs) == total:
                break
        else:
            return _suspicious(
                source,
                jobs,
                diagnostics,
                page_count,
                "pagination_limit",
                "Twilio pagination exceeded the configured safety cap.",
            )

        diagnostics.append(
            _diagnostic(
                "unverified_creation_timestamp",
                DiagnosticSeverity.WARNING,
                "Twilio listing creation timestamps remain uncertain until detail retrieval.",
                count=len(jobs),
            )
        )
        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            diagnostics,
            page_count=page_count,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        _validate_source(source)
        _validate_listing_job(source, job)
        external_id = job.external_job_id
        if external_id is None:
            raise AdapterConfigurationError("Twilio detail requires an external job ID.")
        endpoint = _detail_url(external_id)
        try:
            response = self._client.get(
                endpoint,
                accepted_content_types=("application/json",),
                referer=job.canonical_url,
            )
        except HttpRequestError as error:
            raise ValueError(f"Twilio detail request failed: {error.category.value}") from error
        if response.final_url != endpoint:
            raise ValueError("Twilio detail API redirected.")
        try:
            payload: Any = json.loads(response.body)
            detail = _response_data(payload, "Twilio detail response")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            raise ValueError("Twilio detail response schema was invalid.") from error

        observed_id = str(_positive_int(detail.get("id"), "Twilio detail id"))
        if observed_id != external_id:
            raise ValueError("Twilio detail ID did not match the listing.")
        title = _required_string(detail, "name", "Twilio detail")
        if _normalize_text(title) != job.title_normalized:
            raise ValueError("Twilio detail title did not match the listing.")
        locations = _locations(detail)
        if _normalized_locations(locations) != job.location_normalized:
            raise ValueError("Twilio detail locations did not match the listing.")
        _validate_position_path(detail.get("positionUrl"), external_id)
        public_url = _required_string(detail, "publicUrl", "Twilio detail")
        if public_url != job.canonical_url:
            raise ValueError("Twilio detail public URL did not match the listing.")

        description = _plain_text(
            _required_string(detail, "jobDescription", "Twilio detail")
        )
        if len(description) < 80:
            raise ValueError("Twilio detail description normalized to insufficient text.")
        published_raw, published_at = _published_date(detail.get("efcustomTextPostDate"))
        return NormalizedJob(
            schema_version=1,
            company_id=job.company_id,
            source_type=job.source_type,
            external_job_id=job.external_job_id,
            title_original=job.title_original,
            title_normalized=job.title_normalized,
            location_original=job.location_original,
            location_normalized=job.location_normalized,
            published_at=published_at,
            published_at_raw=published_raw,
            date_basis=DateBasis.PUBLISHED,
            canonical_url=job.canonical_url,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata={
                **job.source_metadata,
                "detail_retrieved": True,
                "visible_date_posted_verified": True,
            },
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != TWILIO_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Twilio adapter requires adapter_key={TWILIO_ADAPTER_KEY}."
        )
    if source.careers_url != TWILIO_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Twilio adapter requires careers_url={TWILIO_CAREERS_URL}."
        )


def _validate_listing_job(source: CompanySource, job: NormalizedJob) -> None:
    if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
        raise AdapterConfigurationError("Twilio detail job does not belong to the source.")
    external_id = job.external_job_id
    if external_id is None or job.canonical_url != _canonical_url(external_id):
        raise AdapterConfigurationError("Twilio detail job identity is inconsistent.")


def _search_url(start: int) -> str:
    return (
        f"{TWILIO_API_ROOT}/search?domain=twilio.com&query=&location=&start={start}&&hl=en"
    )


def _detail_url(external_id: str) -> str:
    return (
        f"{TWILIO_API_ROOT}/position_details?position_id={external_id}"
        "&domain=twilio.com&hl=en"
    )


def _canonical_url(external_id: str) -> str:
    return f"https://jobs.twilio.com/careers/job/{external_id}"


def _response_data(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} root must be an object.")
    if value.get("status") != 200:
        raise ValueError(f"{context} did not report status=200.")
    error = value.get("error")
    if not isinstance(error, Mapping):
        raise ValueError(f"{context} error field must be an object.")
    if error.get("message") not in {"", None} or error.get("body") not in {"", None}:
        raise ValueError(f"{context} reported an error.")
    data = value.get("data")
    if not isinstance(data, Mapping):
        raise ValueError(f"{context} data field must be an object.")
    return data


def _normalize_listing(source: CompanySource, value: object) -> NormalizedJob:
    if not isinstance(value, Mapping):
        raise ValueError("Twilio listing must be an object.")
    external_id = str(_positive_int(value.get("id"), "Twilio job id"))
    title = _required_string(value, "name", "Twilio listing")
    locations = _locations(value)
    _validate_position_path(value.get("positionUrl"), external_id)
    created_raw, created_at = _creation_timestamp(value.get("creationTs"))
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=_normalize_whitespace(title),
        title_normalized=_normalize_text(title),
        location_original=" | ".join(locations),
        location_normalized=_normalized_locations(locations),
        published_at=created_at,
        published_at_raw=created_raw,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=_canonical_url(external_id),
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": TWILIO_ADAPTER_KEY,
            "ats_job_id": value.get("atsJobId"),
            "department": value.get("department"),
            "display_job_id": value.get("displayJobId"),
            "creation_timestamp_unverified": True,
            "work_location_option": value.get("workLocationOption"),
        },
    )


def _locations(value: Mapping[str, object]) -> list[str]:
    raw = value.get("locations")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Twilio job locations must be a non-empty array.")
    locations: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Twilio job locations must contain non-empty strings.")
        normalized = _normalize_whitespace(item)
        if normalized.casefold() not in {item.casefold() for item in locations}:
            locations.append(normalized)
    return locations


def _normalized_locations(locations: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_text(location) for location in locations)


def _validate_position_path(value: object, external_id: str) -> None:
    if value != f"/careers/job/{external_id}":
        raise ValueError("Twilio positionUrl did not match its job ID.")


def _creation_timestamp(value: object) -> tuple[str, datetime]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("Twilio creationTs must be numeric.")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError("Twilio creationTs must be a non-negative finite timestamp.")
    try:
        parsed = datetime.fromtimestamp(numeric, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError("Twilio creationTs was outside the supported range.") from error
    return str(value), parsed


def _published_date(value: object) -> tuple[str, date]:
    if not isinstance(value, list) or len(value) != 1:
        raise ValueError("Twilio detail ecustomTextPostDate must contain one date.")
    raw = value[0]
    if not isinstance(raw, str):
        raise ValueError("Twilio detail publication date must be text.")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as error:
        raise ValueError("Twilio detail publication date was invalid.") from error
    return raw, parsed


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "svg", "noscript"}:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag.casefold() in {"br", "div", "li", "p"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif self.skip_depth == 0 and tag.casefold() in {"div", "li", "p"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html.unescape(value))
    parser.close()
    return _normalize_whitespace("".join(parser.parts))


def _positive_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{context} must be a positive integer.")
    return value


def _required_string(raw: Mapping[str, object], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} {field} must be a non-empty string.")
    return value.strip()


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


def _suspicious(
    source: CompanySource,
    jobs: list[NormalizedJob],
    diagnostics: list[AdapterDiagnostic],
    page_count: int,
    category: str,
    message: str,
) -> AdapterResult:
    diagnostics.append(_diagnostic(category, DiagnosticSeverity.ERROR, message))
    return _result(
        source,
        AdapterOutcome.SUSPICIOUS,
        jobs,
        diagnostics,
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
