"""Reusable adapter for public Eightfold PCSx careers surfaces."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.errors import DetailContentMissing, DetailIdentityMismatch
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

PCSX_ADAPTER_KEY = "pcsx_public_careers"
_PAGE_SIZE = 10
_MAX_PAGES = 100
_HOST_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
_DOMAIN_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")


class PcsxCareersAdapter:
    """Read a complete public PCSx listing collection and deferred details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = PCSX_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        host, domain = _validate_source(source)
        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None

        for page_index in range(_MAX_PAGES):
            endpoint = _search_url(host, domain, page_index * _PAGE_SIZE)
            try:
                response = self._client.get(
                    endpoint,
                    accepted_content_types=("application/json",),
                    referer=source.careers_url,
                )
            except HttpRequestError as error:
                diagnostics.append(request_failure_diagnostic(error))
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else _request_outcome(error),
                    jobs,
                    page_index,
                    diagnostics,
                )
            if response.final_url != endpoint:
                return _failure(
                    source,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    "unexpected_redirect",
                    "PCSx search API redirected.",
                )
            try:
                data = _response_data(json.loads(response.body), "PCSx search response")
                positions = _required_list(data.get("positions"), "PCSx positions")
                total = _non_negative_int(data.get("count"), "PCSx count")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                return _failure(
                    source,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    "unsupported_schema",
                    str(error),
                )
            if len(positions) > _PAGE_SIZE:
                return _suspicious(
                    source,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    "page_size_exceeded",
                    "PCSx returned more jobs than the verified page size.",
                )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                return _suspicious(
                    source,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    "inconsistent_total",
                    "PCSx job count changed during pagination.",
                )
            if not positions and len(jobs) < total:
                return _suspicious(
                    source,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    "premature_empty_page",
                    "PCSx returned an empty page before its reported count.",
                )

            for job_index, raw_job in enumerate(positions):
                try:
                    job = _normalize_listing(source, host, raw_job)
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
                        page_index + 1,
                        diagnostics,
                    )
                external_id = job.external_job_id
                if external_id is None:
                    raise AssertionError("PCSx jobs require an external ID")
                if external_id in seen_ids:
                    return _suspicious(
                        source,
                        jobs,
                        page_index + 1,
                        diagnostics,
                        "duplicate_job_id",
                        "PCSx pagination returned a duplicate job ID.",
                    )
                seen_ids.add(external_id)
                jobs.append(job)

            if len(jobs) > total:
                return _suspicious(
                    source,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    "collection_exceeds_total",
                    "PCSx returned more jobs than its reported count.",
                )
            if len(jobs) == total:
                missing_location_count = sum(
                    job.source_metadata.get("listing_location_missing") is True for job in jobs
                )
                diagnostics.append(
                    _diagnostic(
                        "unverified_creation_timestamp",
                        DiagnosticSeverity.WARNING,
                        "PCSx creation timestamps remain uncertain until detail retrieval.",
                        count=len(jobs),
                    )
                )
                if missing_location_count:
                    diagnostics.append(
                        _diagnostic(
                            "missing_location",
                            DiagnosticSeverity.WARNING,
                            "PCSx listings without locations remain explicit.",
                            count=missing_location_count,
                        )
                    )
                return _result(
                    source,
                    AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
                    jobs,
                    page_index + 1,
                    diagnostics,
                    complete=True,
                )

        return _suspicious(
            source,
            jobs,
            _MAX_PAGES,
            diagnostics,
            "pagination_limit",
            "PCSx pagination exceeded the configured safety cap.",
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        host, domain = _validate_source(source)
        _validate_listing_job(source, job, host)
        external_id = job.external_job_id
        if external_id is None:
            raise AdapterConfigurationError("PCSx detail requires an external job ID.")
        endpoint = _detail_url(host, domain, external_id)
        try:
            response = self._client.get(
                endpoint,
                accepted_content_types=("application/json",),
                referer=job.canonical_url,
            )
        except HttpRequestError as error:
            raise DetailContentMissing(
                f"PCSx detail request failed: {error.category.value}"
            ) from error
        if response.final_url != endpoint:
            raise DetailIdentityMismatch("PCSx detail API redirected.")
        try:
            detail = _response_data(json.loads(response.body), "PCSx detail response")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            raise DetailContentMissing("PCSx detail response schema was invalid.") from error
        observed_id = str(_positive_int(detail.get("id"), "PCSx detail id"))
        if observed_id != external_id:
            raise DetailIdentityMismatch("PCSx detail ID did not match the listing.")
        title = _required_string(detail, "name", "PCSx detail")
        if _normalize_text(title) != job.title_normalized:
            raise DetailIdentityMismatch("PCSx detail title did not match the listing.")
        locations = _locations(detail)
        if not locations:
            locations = ["Location unavailable"]
        if _normalized_locations(locations) != job.location_normalized:
            raise DetailIdentityMismatch("PCSx detail locations did not match the listing.")
        _validate_position_path(detail.get("positionUrl"), external_id)
        if _required_string(detail, "publicUrl", "PCSx detail") != job.canonical_url:
            raise DetailIdentityMismatch("PCSx detail public URL did not match the listing.")
        description = _plain_text(_required_string(detail, "jobDescription", "PCSx detail"))
        if len(description) < 80:
            raise DetailContentMissing("PCSx detail description normalized to insufficient text.")
        posted_raw, posted_at = _detail_timestamp(detail)
        return replace(
            job,
            published_at=posted_at,
            published_at_raw=posted_raw,
            date_basis=DateBasis.UNKNOWN,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata={
                **job.source_metadata,
                "detail_retrieved": True,
                "posted_timestamp_unverified": True,
            },
        )


def _validate_source(source: CompanySource) -> tuple[str, str]:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key", "host", "domain"),
    )
    if parameters["adapter_key"] != PCSX_ADAPTER_KEY:
        raise AdapterConfigurationError(f"PCSx adapter requires adapter_key={PCSX_ADAPTER_KEY}.")
    host = parameters["host"].casefold()
    domain = parameters["domain"].casefold()
    if _HOST_PATTERN.fullmatch(host) is None or _DOMAIN_PATTERN.fullmatch(domain) is None:
        raise AdapterConfigurationError("PCSx host and domain must be plain DNS names.")
    if source.careers_url is None:
        raise AdapterConfigurationError("PCSx adapter requires careers_url.")
    parsed = urlsplit(source.careers_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/careers"
        or parse_qs(parsed.query) != {"domain": [domain], "hl": ["en"]}
        or parsed.fragment
    ):
        raise AdapterConfigurationError(
            "PCSx careers_url must be the configured HTTPS host /careers?domain=...&hl=en URL."
        )
    return host, domain


def _validate_listing_job(source: CompanySource, job: NormalizedJob, host: str) -> None:
    if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
        raise AdapterConfigurationError("PCSx detail job does not belong to the source.")
    external_id = job.external_job_id
    if external_id is None or job.canonical_url != _canonical_url(host, external_id):
        raise AdapterConfigurationError("PCSx detail job identity is inconsistent.")


def _search_url(host: str, domain: str, start: int) -> str:
    return f"https://{host}/api/pcsx/search?domain={domain}&query=&location=&start={start}&&hl=en"


def _detail_url(host: str, domain: str, external_id: str) -> str:
    return (
        f"https://{host}/api/pcsx/position_details?position_id={external_id}&domain={domain}&hl=en"
    )


def _canonical_url(host: str, external_id: str) -> str:
    return f"https://{host}/careers/job/{external_id}"


def _response_data(value: object, context: str) -> Mapping[object, object]:
    root = _required_mapping(value, context)
    if root.get("status") != 200:
        raise ValueError(f"{context} did not report status=200.")
    error = _required_mapping(root.get("error"), f"{context} error")
    if error.get("message") not in {"", None} or error.get("body") not in {"", None}:
        raise ValueError(f"{context} reported an error.")
    return _required_mapping(root.get("data"), f"{context} data")


def _normalize_listing(source: CompanySource, host: str, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "PCSx listing")
    external_id = str(_positive_int(raw.get("id"), "PCSx job id"))
    title = _required_string(raw, "name", "PCSx listing")
    locations = _locations(raw)
    location_missing = not locations
    if location_missing:
        locations = ["Location unavailable"]
    _validate_position_path(raw.get("positionUrl"), external_id)
    created_raw, created_at = _timestamp(raw.get("creationTs"), "PCSx creationTs")
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
        canonical_url=_canonical_url(host, external_id),
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": PCSX_ADAPTER_KEY,
            "ats_job_id": raw.get("atsJobId"),
            "department": raw.get("department"),
            "display_job_id": raw.get("displayJobId"),
            "creation_timestamp_unverified": True,
            "listing_location_missing": location_missing,
            "work_location_option": raw.get("workLocationOption"),
        },
    )


def _locations(value: Mapping[object, object]) -> list[str]:
    raw = _required_list(value.get("locations"), "PCSx locations")
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("PCSx locations must contain non-empty strings.")
        normalized = _normalize_whitespace(item)
        if normalized.casefold() not in seen:
            result.append(normalized)
            seen.add(normalized.casefold())
    return result


def _normalized_locations(locations: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_text(location) for location in locations)


def _validate_position_path(value: object, external_id: str) -> None:
    if value != f"/careers/job/{external_id}":
        raise ValueError("PCSx positionUrl did not match its job ID.")


def _detail_timestamp(detail: Mapping[object, object]) -> tuple[str, datetime]:
    posted = detail.get("postedTs")
    external = detail.get("externallyPostedTs")
    if posted != external:
        raise ValueError("PCSx posted timestamps did not agree.")
    return _timestamp(posted, "PCSx postedTs")


def _timestamp(value: object, field: str) -> tuple[str, datetime]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be numeric.")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{field} must be a non-negative finite timestamp.")
    try:
        parsed = datetime.fromtimestamp(numeric, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError(f"{field} was outside the supported range.") from error
    return str(value), parsed


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


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _required_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    return value


def _required_string(raw: Mapping[object, object], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} {field} must be a non-empty string.")
    return value.strip()


def _positive_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{context} must be a positive integer.")
    return value


def _non_negative_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer.")
    return value


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


def _failure(
    source: CompanySource,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    category: str,
    message: str,
) -> AdapterResult:
    diagnostics.append(_diagnostic(category, DiagnosticSeverity.ERROR, message))
    return _result(
        source,
        AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
        jobs,
        page_count,
        diagnostics,
    )


def _suspicious(
    source: CompanySource,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    category: str,
    message: str,
) -> AdapterResult:
    diagnostics.append(_diagnostic(category, DiagnosticSeverity.ERROR, message))
    return _result(source, AdapterOutcome.SUSPICIOUS, jobs, page_count, diagnostics)


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
